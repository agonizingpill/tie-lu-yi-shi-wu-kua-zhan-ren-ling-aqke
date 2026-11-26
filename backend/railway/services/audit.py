from fastapi import HTTPException

from railway.db import connect
from railway.enums import SearchState
from railway.models import audits as audit_model
from railway.models.searches import get_search
from railway.services.encoding import COLOR_WEIGHT, ranked_hits
from railway.services.recall import snapshot_bags

VARIANTS = ("baseline", "variant")
TOP_N = 12
BATCH = 200


def check_observer(user):
    if user["role"] != "observer":
        raise HTTPException(403, "仅票务稽核可发起权重稽核")


def start(user):
    check_observer(user)
    with connect() as db:
        audit = audit_model.start_audit(db, user, COLOR_WEIGHT)
    return audit


def listing(user):
    check_observer(user)
    with connect() as db:
        return audit_model.audits(db)


def detail(audit_id, user):
    check_observer(user)
    with connect() as db:
        audit = audit_model.get_audit(db, audit_id)
        rows = audit_model.samples(db, audit_id)
        return {"audit": audit, "samples": rows, "summary": summarize(rows)}


def run(audit_id, user):
    check_observer(user)
    with connect() as db:
        audit = audit_model.get_audit(db, audit_id, lock=True)
        pending = audit_model.pending(db, audit_id, BATCH)
    processed = 0
    while pending:
        for sample in pending:
            _score_sample(audit, sample["search_id"])
        processed += len(pending)
        with connect() as db:
            pending = audit_model.pending(db, audit_id, BATCH)
    with connect() as db:
        remaining = audit_model.pending_count(db, audit_id)
        audit_model.set_status(db, audit_id, "complete" if remaining == 0 else "running")
    return {"audit_id": audit_id, "processed": processed, "remaining": remaining}


def _score_sample(audit, search_id):
    with connect() as db:
        search = get_search(db, search_id)
        bags = snapshot_bags(db, search_id)
        if search["status"] != SearchState.RANKED or not bags:
            # 首次打分记录无法复现时同样单列，避免混入命中率分母。
            db.execute("UPDATE weight_audit_samples SET has_snapshot = false WHERE audit_id = %s AND search_id = %s",
                       (audit["id"], search_id))
            return
        sample = db.execute("""
            SELECT seal_id FROM weight_audit_samples WHERE audit_id = %s AND search_id = %s
        """, (audit["id"], search_id)).fetchone()
        weights = {"baseline": audit["baseline_weight"], "variant": audit["variant_weight"]}
        for variant in VARIANTS:
            hits = ranked_hits(search, bags, color_weight=weights[variant], limit=None)
            rank = next((position for position, hit in enumerate(hits, 1)
                         if hit["seal_id"] == sample["seal_id"]), None)
            score = hits[rank - 1]["score"] if rank else None
            audit_model.save_result(db, audit["id"], search_id, variant, rank, score, len(bags),
                                    rank is not None and rank <= TOP_N)


def summarize(rows):
    scored = [row for row in rows if row["has_snapshot"]
              and row["baseline_hit"] is not None and row["variant_hit"] is not None]
    missing = [row for row in rows if not row["has_snapshot"]]
    unresolved = [row for row in rows if row["has_snapshot"] and row not in scored]
    drops = [row for row in scored if row["baseline_hit"] and not row["variant_hit"]]
    gains = [row for row in scored if row["variant_hit"] and not row["baseline_hit"]]
    total = len(scored)
    baseline_hits = sum(bool(row["baseline_hit"]) for row in scored)
    variant_hits = sum(bool(row["variant_hit"]) for row in scored)
    return {
        "top_n": TOP_N,
        "samples": len(rows),
        "scored": total,
        "missing_snapshot": len(missing),
        "unresolved": len(unresolved),
        "baseline_hits": baseline_hits,
        "variant_hits": variant_hits,
        "baseline_rate": round(baseline_hits / total, 4) if total else 0,
        "variant_rate": round(variant_hits / total, 4) if total else 0,
        "dropped": [{"search_id": row["search_id"], "seal_id": row["seal_id"],
                     "baseline_rank": row["baseline_rank"], "variant_rank": row["variant_rank"]}
                    for row in drops],
        "gained": [{"search_id": row["search_id"], "seal_id": row["seal_id"],
                    "baseline_rank": row["baseline_rank"], "variant_rank": row["variant_rank"]}
                   for row in gains],
        "missing_search_ids": [row["search_id"] for row in missing],
    }
