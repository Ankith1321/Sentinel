import json
import logging
import threading
from dataclasses import dataclass

import numpy as np

from backend.app import store
from ingestion.answer_checks import check_answer
from ingestion.config import VERIFIED_MATCH_THRESHOLD
from ingestion.retriever import QUERY_SYMBOL, get_model

logger = logging.getLogger(__name__)


class ApprovalRejected(ValueError):
    pass


@dataclass(frozen=True)
class VerifiedMatch:
    id: int
    question: str
    answer: str
    sources: list[dict]
    similarity: float
    reviewed_at: str | None


@dataclass(frozen=True)
class _Entries:
    rows: list
    vectors: np.ndarray


_entries: _Entries | None = None
_lock = threading.Lock()


def embed(texts: list[str]) -> np.ndarray:
    return np.asarray(get_model().encode(texts, normalize_embeddings=True), dtype=np.float32)


def invalidate() -> None:
    global _entries
    with _lock:
        _entries = None


def load_entries() -> _Entries:
    global _entries
    with _lock:
        if _entries is None:
            rows = store.approved_verified_answers()
            vectors = embed([r["question"] for r in rows]) if rows else np.zeros((0, 1), dtype=np.float32)
            _entries = _Entries(rows=rows, vectors=vectors)
        return _entries


def symbols_covered(question: str, stored_question: str) -> bool:
    return all(symbol in stored_question for symbol in QUERY_SYMBOL.findall(question))


def changed_sources(row) -> list[str]:
    snapshot: dict[str, str] = json.loads(row["source_hashes_json"])
    current = store.content_hashes(list(snapshot))
    return sorted(path for path, digest in snapshot.items() if current.get(path, "") != digest)


def find_match(question: str, threshold: float = VERIFIED_MATCH_THRESHOLD) -> VerifiedMatch | None:
    entries = load_entries()
    if not entries.rows:
        return None

    similarities = entries.vectors @ embed([question])[0]
    for index in np.argsort(-similarities):
        similarity = float(similarities[index])
        if similarity < threshold:
            return None
        row = entries.rows[index]
        if not symbols_covered(question, row["question"]):
            continue
        changed = changed_sources(row)
        if changed:
            store.set_verified_status(row["id"], "stale", f"Source changed: {', '.join(changed)}")
            invalidate()
            logger.info("verified answer %d went stale: %s", row["id"], changed)
            continue
        return VerifiedMatch(
            id=row["id"],
            question=row["question"],
            answer=row["answer"],
            sources=json.loads(row["sources_json"]),
            similarity=round(similarity, 4),
            reviewed_at=row["reviewed_at"],
        )
    return None


def approve(answer_id: int, edited_answer: str | None = None) -> None:
    row = store.get_verified_answer(answer_id)
    if row is None:
        raise KeyError(answer_id)

    answer = (edited_answer or row["answer"]).strip()
    sources = json.loads(row["sources_json"])
    checks = check_answer(answer, [{"content": s.get("preview") or ""} for s in sources])
    if not checks.cited_sources:
        raise ApprovalRejected("A verified answer must cite at least one of its sources, like [S1].")
    if checks.invalid_citations:
        raise ApprovalRejected(f"The answer cites sources that do not exist: {checks.invalid_citations}")

    paths = sorted({s["path"] for s in sources if s.get("path")})
    current = store.content_hashes(paths)
    store.approve_verified_answer(answer_id, answer, {path: current.get(path, "") for path in paths})
    invalidate()


def approve_all_pending() -> tuple[list[int], list[dict]]:
    approved: list[int] = []
    skipped: list[dict] = []
    for row in store.list_verified_answers("pending", 10_000, 0)[0]:
        try:
            approve(row["id"])
            approved.append(row["id"])
        except ApprovalRejected as error:
            skipped.append({"id": row["id"], "question": row["question"], "reason": str(error)})
    return approved, skipped


def set_status(answer_id: int, status: str) -> None:
    if store.get_verified_answer(answer_id) is None:
        raise KeyError(answer_id)
    store.set_verified_status(answer_id, status)
    invalidate()


def remove(answer_id: int) -> bool:
    removed = store.delete_verified_answer(answer_id)
    invalidate()
    return removed


def mark_stale(changed_paths: set[str]) -> int:
    marked = store.mark_verified_stale(changed_paths) if changed_paths else 0
    if marked:
        invalidate()
    return marked
