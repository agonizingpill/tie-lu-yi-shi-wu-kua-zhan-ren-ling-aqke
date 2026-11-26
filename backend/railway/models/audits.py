from fastapi import HTTPException

from railway.services.encoding import COLOR_WEIGHT


def audits(db):
    return db.execute("""
        SELECT a.id, a.baseline_weight, a.variant_weight, a.started_at, a.status, a.created_by,
               (SELECT COUNT(*) FROM weight_audit_samples s WHERE s.audit_id = a.id) AS sample_count,
               (SELECT COUNT(*) FROM weight_audit_samples s
                WHERE s.audit_id = a.id AND NOT s.has_snapshot) AS missing_snapshot,
               (SELECT COUNT(*) FROM weight_audit_results r
                WHERE r.audit_id = a.id AND r.variant = 'variant') AS scored_count
        FROM weight_audits a ORDER BY a.id DESC LIMIT 50
    """).fetchall()


def get_audit(db, audit_id, *, lock=False):
    suffix = " FOR UPDATE" if lock else ""
    audit = db.execute("SELECT * FROM weight_audits WHERE id = %s" + suffix, (audit_id,)).fetchone()
    if not audit:
        raise HTTPException(404, "未找到权重稽核")
    return audit


def start_audit(db, user, baseline_weight=COLOR_WEIGHT):
    # 先锁 claims 表，让并发中的交付事务在取样本前落定：
    # 开测时仍在途的交付若先提交则计入本轮，后提交的留给下一轮，绝不重复。
    db.execute("LOCK TABLE claims IN SHARE MODE")
    # 用 clock_timestamp 而非 now()：若曾等待交付事务，快照点须晚于其提交时间。
    started_at = db.execute("SELECT clock_timestamp() AS at").fetchone()["at"]
    audit = db.execute("""
        INSERT INTO weight_audits (baseline_weight, variant_weight, started_at, created_by)
        VALUES (%s, %s, %s, %s) RETURNING *
    """, (baseline_weight, baseline_weight / 2, started_at, user["email"])).fetchone()
    db.execute("""
        INSERT INTO weight_audit_samples (audit_id, search_id, seal_id, released_at, has_snapshot)
        SELECT %s, c.search_id, c.seal_id, c.released_at,
               EXISTS (SELECT 1 FROM recall_snapshots s WHERE s.search_id = c.search_id)
        FROM claims c
        WHERE c.status = 'released' AND c.released_at IS NOT NULL
    """, (audit["id"],))
    return audit


def samples(db, audit_id):
    return db.execute("""
        SELECT s.search_id, s.seal_id, s.released_at, s.has_snapshot,
               ss.category, ss.color, ss.description, ss.travel_on, ss.train_no,
               b.true_rank AS baseline_rank, b.true_score AS baseline_score, b.hit AS baseline_hit,
               b.compared AS baseline_compared,
               v.true_rank AS variant_rank, v.true_score AS variant_score, v.hit AS variant_hit
        FROM weight_audit_samples s
        JOIN search_slips ss ON ss.id = s.search_id
        LEFT JOIN weight_audit_results b ON b.audit_id = s.audit_id AND b.search_id = s.search_id
            AND b.variant = 'baseline'
        LEFT JOIN weight_audit_results v ON v.audit_id = s.audit_id AND v.search_id = s.search_id
            AND v.variant = 'variant'
        WHERE s.audit_id = %s
        ORDER BY s.search_id
    """, (audit_id,)).fetchall()


def pending(db, audit_id, limit):
    return db.execute("""
        SELECT s.search_id FROM weight_audit_samples s
        WHERE s.audit_id = %s AND s.has_snapshot
          AND (SELECT COUNT(*) FROM weight_audit_results r
               WHERE r.audit_id = s.audit_id AND r.search_id = s.search_id) < 2
        ORDER BY s.search_id LIMIT %s
    """, (audit_id, limit)).fetchall()


def pending_count(db, audit_id):
    return db.execute("""
        SELECT COUNT(*) AS total FROM weight_audit_samples s
        WHERE s.audit_id = %s AND s.has_snapshot
          AND (SELECT COUNT(*) FROM weight_audit_results r
               WHERE r.audit_id = s.audit_id AND r.search_id = s.search_id) < 2
    """, (audit_id,)).fetchone()["total"]


def save_result(db, audit_id, search_id, variant, rank, score, compared, hit):
    db.execute("""
        INSERT INTO weight_audit_results
            (audit_id, search_id, variant, true_rank, true_score, compared, hit)
        VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
    """, (audit_id, search_id, variant, rank, score, compared, hit))


def set_status(db, audit_id, status):
    db.execute("UPDATE weight_audits SET status = %s WHERE id = %s", (status, audit_id))
