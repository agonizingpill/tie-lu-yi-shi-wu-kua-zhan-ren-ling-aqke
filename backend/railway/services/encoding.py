from collections import defaultdict

from sklearn.feature_extraction import FeatureHasher
from sklearn.metrics.pairwise import cosine_similarity

from railway.text import description_tokens, normalized

DIMENSIONS = 64
FEATURE_LIMIT = 160
ALGORITHM = "FeatureHasher + sparse cosine"
CATEGORY_WEIGHT = 3.0
COLOR_WEIGHT = 2.0
MIN_SCORE = 0.2


def features(row, *, category_weight=CATEGORY_WEIGHT, color_weight=COLOR_WEIGHT):
    encoded = {"category:" + normalized(row["category"]): category_weight,
               "color:" + normalized(row["color"]): color_weight}
    if row["train_no"]:
        encoded["train:" + normalized(row["train_no"])] = 1.0
    encoded.update({"public:" + token: 1.0 for token in sorted(description_tokens(row["description"]))[:FEATURE_LIMIT]})
    return encoded


def bucket_map(hasher, words):
    packed = defaultdict(set)
    words = sorted(words)
    rows = hasher.transform([{word: 1} for word in words])
    for word, index in zip(words, rows.indices, strict=True):
        packed[int(index)].add(word)
    return packed


def ranked_hits(clue, bags, *, category_weight=CATEGORY_WEIGHT, color_weight=COLOR_WEIGHT, limit=None):
    hasher = FeatureHasher(n_features=DIMENSIONS, input_type="dict", alternate_sign=True)
    query = features(clue, category_weight=category_weight, color_weight=color_weight)
    reference = [features(bag, category_weight=category_weight, color_weight=color_weight) for bag in bags]
    vectors = hasher.fit_transform([query, *reference])
    scores = cosine_similarity(vectors[0:1], vectors[1:]).ravel() if bags else []
    hits = []
    for index, value in enumerate(scores):
        if value < MIN_SCORE:
            continue
        candidate = reference[index]
        buckets = bucket_map(hasher, query.keys() | candidate.keys())
        overlaps = query.keys() & candidate.keys()
        exact_tokens = sum(word.startswith("public:") for word in overlaps)
        distinct_word_slots = sum(
            len(words) > 1 and bool(words & query.keys()) and bool(words & candidate.keys())
            for words in buckets.values()
        )
        hits.append({
            "seal_id": bags[index]["seal_id"],
            "score": float(round(min(1, value), 5)),
            "exact_features": len(overlaps),
            "collision_slots": distinct_word_slots,
            "auditable": exact_tokens > 0 and clue["category"] == bags[index]["category"],
        })
    hits.sort(key=lambda hit: (-hit["score"], hit["seal_id"]))
    return hits if limit is None else hits[:limit]


def score_clues(clue, bags):
    return ranked_hits(clue, bags, limit=12)
