import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from ingestion.config import COLLECTION_NAME, EMBEDDING_MODEL, PROJECT_ROOT, SUPERSET_REPO
from ingestion.retriever import retrieve

QA_SET_PATH = PROJECT_ROOT / "eval" / "qa_set.json"
RESULTS_DIR = PROJECT_ROOT / "eval" / "results"
CUTOFFS = (1, 5, 10)

logger = logging.getLogger("sentinel.eval")


def load_qa_set() -> list[dict]:
    return json.loads(QA_SET_PATH.read_text(encoding="utf-8"))


def validate_ground_truth(qa_set: list[dict]) -> list[str]:
    problems = []

    for item in qa_set:
        for rel_path in item["expected_paths"]:
            file_path = SUPERSET_REPO / rel_path

            if not file_path.is_file():
                problems.append(f"{item['id']}: missing file {rel_path}")
                continue

            needle = item.get("must_contain")
            if needle and needle not in file_path.read_text(encoding="utf-8", errors="ignore"):
                problems.append(f"{item['id']}: {rel_path} does not contain {needle!r}")

    return problems


def first_hit_rank(retrieved_paths: list[str], expected_paths: list[str]) -> int | None:
    expected = set(expected_paths)

    for rank, path in enumerate(retrieved_paths, start=1):
        if path in expected:
            return rank

    return None


def score(qa_set: list[dict], retrieve_fn, depth: int, mode: str | None = None) -> dict:
    rows = []

    for item in qa_set:
        matches = retrieve_fn(item["question"], top_k=depth, mode=mode)
        retrieved_paths = [m["metadata"]["path"] for m in matches]
        rank = first_hit_rank(retrieved_paths, item["expected_paths"])

        rows.append(
            {
                "id": item["id"],
                "type": item["type"],
                "question": item["question"],
                "expected_paths": item["expected_paths"],
                "rank": rank,
                "retrieved_paths": retrieved_paths,
            }
        )

    return {"rows": rows, "summary": summarise(rows)}


def summarise(rows: list[dict]) -> dict:
    def metrics(subset: list[dict]) -> dict:
        total = len(subset)
        result = {"n": total}

        for k in CUTOFFS:
            hits = sum(1 for r in subset if r["rank"] is not None and r["rank"] <= k)
            result[f"hit@{k}"] = round(hits / total, 4) if total else 0.0

        reciprocal = [1 / r["rank"] for r in subset if r["rank"] is not None]
        result["mrr"] = round(sum(reciprocal) / total, 4) if total else 0.0
        return result

    by_type = defaultdict(list)
    for row in rows:
        by_type[row["type"]].append(row)

    return {
        "overall": metrics(rows),
        "by_type": {name: metrics(subset) for name, subset in sorted(by_type.items())},
    }


def log_report(report: dict) -> None:
    overall = report["summary"]["overall"]
    logger.info("questions=%d  hit@1=%.1f%%  hit@5=%.1f%%  hit@10=%.1f%%  MRR=%.3f",
                overall["n"], overall["hit@1"] * 100, overall["hit@5"] * 100,
                overall["hit@10"] * 100, overall["mrr"])

    for name, m in report["summary"]["by_type"].items():
        logger.info("  %-10s n=%-3d hit@5=%.1f%%  MRR=%.3f", name, m["n"], m["hit@5"] * 100, m["mrr"])

    misses = [r for r in report["rows"] if r["rank"] is None or r["rank"] > 5]
    for row in misses:
        logger.info("MISS %s (rank=%s) %s", row["id"], row["rank"], row["question"])
        logger.info("     expected: %s", ", ".join(row["expected_paths"]))
        logger.info("     got:      %s", ", ".join(dict.fromkeys(row["retrieved_paths"][:5])))


def save_report(report: dict, label: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = RESULTS_DIR / f"{stamp}_{label}.json"
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Score Sentinel retrieval against eval/qa_set.json")
    parser.add_argument("--validate", action="store_true", help="only check expected files exist")
    parser.add_argument("--label", default="baseline", help="name stored in the result file")
    parser.add_argument("--mode", default="vector", choices=["vector", "keyword", "hybrid", "hybrid_rerank"])
    parser.add_argument("--depth", type=int, default=max(CUTOFFS), help="chunks to retrieve per question")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(message)s", stream=sys.stdout)
    logger.setLevel(logging.INFO)
    qa_set = load_qa_set()

    problems = validate_ground_truth(qa_set)
    for problem in problems:
        logger.error(problem)
    if problems:
        return 1

    logger.info("ground truth ok: %d questions", len(qa_set))
    if args.validate:
        return 0

    report = score(qa_set, retrieve, args.depth, args.mode)
    report["config"] = {"mode": args.mode, "collection": COLLECTION_NAME, "embedding_model": EMBEDDING_MODEL}
    log_report(report)
    logger.info("saved %s", save_report(report, args.label))
    return 0


if __name__ == "__main__":
    sys.exit(main())
