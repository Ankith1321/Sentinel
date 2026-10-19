import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone

from eval.run_eval import RESULTS_DIR, load_qa_set
from ingestion import rag_service
from ingestion.answer_checks import check_answer
from ingestion.config import LOCAL_LLM_MODEL, LOCAL_LLM_QUANT, MAX_ANSWER_TOKENS, PROJECT_ROOT
from ingestion.llm import get_provider

UNANSWERABLE_PATH = PROJECT_ROOT / "eval" / "unanswerable.json"
TOP_K = 5

logger = logging.getLogger("sentinel.answer_eval")


def generate(question: str, variant: str) -> tuple[dict, str, float]:
    prepared = rag_service.prepare(question, TOP_K, [], None, None, None)

    started = time.perf_counter()
    answer = get_provider().complete(rag_service.SYSTEM_PROMPTS[variant], prepared["messages"], MAX_ANSWER_TOKENS)
    return prepared, answer, time.perf_counter() - started


def rate(count: int, total: int) -> float:
    return round(count / total, 3) if total else 0.0


def evaluate_answerable(qa_set: list[dict], variant: str) -> list[dict]:
    rows = []

    for item in qa_set:
        prepared, answer, seconds = generate(item["question"], variant)
        contexts = prepared["contexts"]
        checks = check_answer(answer, contexts)
        expected = set(item["expected_paths"])
        retrieved = {c["metadata"]["path"] for c in contexts}
        cited_paths = {contexts[n - 1]["metadata"]["path"] for n in checks.cited_sources}

        rows.append(
            {
                "id": item["id"],
                "question": item["question"],
                "retrieval_hit": bool(expected & retrieved),
                "answer": answer,
                "seconds": round(seconds, 2),
                "cited": bool(checks.cited_sources),
                "invalid_citations": bool(checks.invalid_citations),
                "cites_expected": bool(expected & cited_paths),
                "unsupported_terms": checks.unsupported_terms,
                "abstained": checks.abstained,
                "needs_review": checks.needs_review,
            }
        )
        logger.info("%s hit=%s cited=%s unsupported=%d %.1fs", item["id"], rows[-1]["retrieval_hit"],
                    rows[-1]["cited"], len(checks.unsupported_terms), seconds)

    return rows


def evaluate_unanswerable(questions: list[dict], variant: str) -> list[dict]:
    rows = []

    for item in questions:
        prepared, answer, seconds = generate(item["question"], variant)
        checks = check_answer(answer, prepared["contexts"])
        rows.append({"id": item["id"], "question": item["question"], "answer": answer,
                     "abstained": checks.abstained, "seconds": round(seconds, 2)})
        logger.info("%s abstained=%s", item["id"], checks.abstained)

    return rows


def summarise(answerable: list[dict], unanswerable: list[dict]) -> dict:
    hits = [r for r in answerable if r["retrieval_hit"]]

    return {
        "answerable_n": len(answerable),
        "retrieval_hit_rate": rate(len(hits), len(answerable)),
        "cites_a_source": rate(sum(r["cited"] for r in answerable), len(answerable)),
        "invalid_citation_rate": rate(sum(r["invalid_citations"] for r in answerable), len(answerable)),
        "cites_expected_file_when_retrieved": rate(sum(r["cites_expected"] for r in hits), len(hits)),
        "answers_naming_unsupported_terms": rate(
            sum(bool(r["unsupported_terms"]) for r in answerable), len(answerable)
        ),
        "wrongly_abstained_when_retrieved": rate(sum(r["abstained"] for r in hits), len(hits)),
        "flagged_needs_review": rate(sum(r["needs_review"] for r in answerable), len(answerable)),
        "avg_seconds": round(sum(r["seconds"] for r in answerable) / max(1, len(answerable)), 2),
        "unanswerable_n": len(unanswerable),
        "correctly_abstained_on_unanswerable": rate(sum(r["abstained"] for r in unanswerable), len(unanswerable)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Score what the LLM says, not just what retrieval returns")
    parser.add_argument("--prompt", default="v1", choices=sorted(rag_service.SYSTEM_PROMPTS))
    parser.add_argument("--limit", type=int, default=0, help="only the first N answerable questions")
    parser.add_argument("--label", default="answers")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(message)s", stream=sys.stdout)
    logger.setLevel(logging.INFO)
    rag_service.PROMPT_VARIANT = args.prompt

    qa_set = load_qa_set()
    if args.limit:
        qa_set = qa_set[: args.limit]
    unanswerable = json.loads(UNANSWERABLE_PATH.read_text(encoding="utf-8"))

    answerable_rows = evaluate_answerable(qa_set, args.prompt)
    unanswerable_rows = evaluate_unanswerable(unanswerable, args.prompt)
    summary = summarise(answerable_rows, unanswerable_rows)

    report = {
        "config": {"model": LOCAL_LLM_MODEL, "quantization": LOCAL_LLM_QUANT or "fp16", "prompt": args.prompt},
        "summary": summary,
        "answerable": answerable_rows,
        "unanswerable": unanswerable_rows,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = RESULTS_DIR / f"{stamp}_{args.label}.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    for key, value in summary.items():
        logger.info("%-40s %s", key, value)
    logger.info("saved %s", output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
