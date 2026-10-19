import json
import logging
import sys

import numpy as np

from backend.app.verified import embed, symbols_covered
from ingestion.config import EMBEDDING_MODEL, PROJECT_ROOT, VERIFIED_MATCH_THRESHOLD

PAIRS_PATH = PROJECT_ROOT / "eval" / "verified_matching.json"
THRESHOLDS = [round(t, 2) for t in np.arange(0.80, 0.99, 0.01)]

logger = logging.getLogger("sentinel.matching_eval")


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(message)s", stream=sys.stdout)
    logger.setLevel(logging.INFO)
    pairs = json.loads(PAIRS_PATH.read_text(encoding="utf-8"))

    stored = embed([p["stored"] for p in pairs])
    probes = embed([p["probe"] for p in pairs])
    similarity = np.sum(stored * probes, axis=1)
    guarded = [symbols_covered(p["probe"], p["stored"]) for p in pairs]

    logger.info("model %s, %d pairs (%d should match)", EMBEDDING_MODEL, len(pairs), sum(p["match"] for p in pairs))
    logger.info("threshold  matched  false-matches  missed  precision  recall")
    for threshold in THRESHOLDS:
        decided = [s >= threshold and g for s, g in zip(similarity, guarded, strict=True)]
        hits = sum(d and p["match"] for d, p in zip(decided, pairs, strict=True))
        false = sum(d and not p["match"] for d, p in zip(decided, pairs, strict=True))
        missed = sum(p["match"] and not d for d, p in zip(decided, pairs, strict=True))
        precision = hits / (hits + false) if hits + false else 1.0
        recall = hits / sum(p["match"] for p in pairs)
        marker = "  <- configured" if abs(threshold - VERIFIED_MATCH_THRESHOLD) < 1e-9 else ""
        logger.info(f"{threshold:9.2f} {hits:8d} {false:14d} {missed:7d} {precision:10.2f} {recall:7.2f}{marker}")

    logger.info("closest near-misses (must stay below the threshold):")
    for i in np.argsort(-similarity):
        if not pairs[i]["match"]:
            logger.info(f"  {similarity[i]:.3f}  guard={'pass' if guarded[i] else 'blocks'}  "
                        f"{pairs[i]['stored']!r} vs {pairs[i]['probe']!r}")
            if similarity[i] < 0.8:
                break
    logger.info("weakest paraphrases (should stay above it):")
    for i in np.argsort(similarity):
        if pairs[i]["match"]:
            logger.info(f"  {similarity[i]:.3f}  {pairs[i]['stored']!r} vs {pairs[i]['probe']!r}")
            if similarity[i] > 0.9:
                break
    return 0


if __name__ == "__main__":
    sys.exit(main())
