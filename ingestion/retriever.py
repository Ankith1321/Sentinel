import logging
import re
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

import chromadb
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder, SentenceTransformer

from ingestion.config import (
    CHROMA_PATH,
    COLLECTION_NAME,
    EMBEDDING_MODEL,
    QUERY_PREFIX,
    RERANK_MODEL,
    RETRIEVAL_MODE,
    SYMBOL_WEIGHT,
    TEST_PATH_PENALTY,
)

logger = logging.getLogger(__name__)

Mode = Literal["vector", "keyword", "hybrid", "hybrid_rerank"]

RRF_K = 60
MIN_CANDIDATE_POOL = 20
PATH_FILTER_OVERFETCH = 8
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")
TEST_PATH_MARKERS = (
    "/tests/", "/test_", "_test.", "_tests.", ".test.", ".spec.", "/spec/", "__tests__", ".stories.",
)
CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
DEFINITION = re.compile(
    r"^[ \t]*(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:async\s+)?(?:abstract\s+)?"
    r"(?:class|def|function|interface|type|enum|const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)",
    flags=re.MULTILINE,
)
QUERY_SYMBOL = re.compile(
    r"\b(?:[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+|[a-z]+[A-Z][A-Za-z0-9]*|[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*)\b"
)


@dataclass(frozen=True)
class KeywordIndex:
    bm25: BM25Okapi
    ids: list[str]
    documents: list[str]
    metadatas: list[dict]
    definitions: dict[str, list[int]]


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    return SentenceTransformer(EMBEDDING_MODEL)


@lru_cache(maxsize=1)
def get_reranker() -> CrossEncoder:
    return CrossEncoder(RERANK_MODEL)


@lru_cache(maxsize=1)
def get_collection():
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    return client.get_collection(name=COLLECTION_NAME)


def tokenize_for_keywords(text: str) -> list[str]:
    tokens: list[str] = []

    for identifier in IDENTIFIER.findall(text):
        lowered = identifier.lower()
        tokens.append(lowered)

        parts = [
            piece.lower()
            for chunk in CAMEL_BOUNDARY.split(identifier)
            for piece in chunk.split("_")
            if piece
        ]
        if len(parts) > 1:
            tokens.extend(parts)

    return tokens


def build_keyword_index() -> KeywordIndex:
    collection = get_collection()
    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict] = []
    page_size = 5000

    for offset in range(0, collection.count(), page_size):
        page = collection.get(limit=page_size, offset=offset, include=["documents", "metadatas"])
        ids.extend(page["ids"])
        documents.extend(page["documents"])
        metadatas.extend(page["metadatas"])

    bm25 = BM25Okapi([tokenize_for_keywords(d) for d in documents])
    definitions: dict[str, list[int]] = {}
    for i, document in enumerate(documents):
        for name in set(DEFINITION.findall(document)):
            definitions.setdefault(name, []).append(i)
    logger.info("keyword index built over %d chunks, %d defined symbols", len(ids), len(definitions))
    return KeywordIndex(bm25=bm25, ids=ids, documents=documents, metadatas=metadatas, definitions=definitions)


_keyword_index: KeywordIndex | None = None
_keyword_lock = threading.Lock()


def get_keyword_index() -> KeywordIndex:
    global _keyword_index
    if _keyword_index is None:
        with _keyword_lock:
            if _keyword_index is None:
                _keyword_index = build_keyword_index()
    return _keyword_index


def refresh_keyword_index() -> None:
    # Build the replacement first and swap it in, so queries keep using the old index meanwhile.
    global _keyword_index
    fresh = build_keyword_index()
    with _keyword_lock:
        _keyword_index = fresh


def keyword_index_size() -> int | None:
    return len(_keyword_index.ids) if _keyword_index is not None else None


def passes_filters(metadata: dict, language: str | None, path_prefix: str | None) -> bool:
    if language and metadata.get("language") != language:
        return False

    if path_prefix and not str(metadata.get("path", "")).startswith(path_prefix):
        return False

    return True


def vector_search(query: str, limit: int, language: str | None, path_prefix: str | None) -> list[dict]:
    embedding = get_model().encode([QUERY_PREFIX + query], normalize_embeddings=True)[0].tolist()
    fetch = limit * PATH_FILTER_OVERFETCH if path_prefix else limit

    results = get_collection().query(
        query_embeddings=[embedding],
        n_results=fetch,
        where={"language": language} if language else None,
        include=["documents", "metadatas", "distances"],
    )

    hits = [
        {
            "id": results["ids"][0][i],
            "content": results["documents"][0][i],
            "metadata": results["metadatas"][0][i],
            "distance": results["distances"][0][i],
        }
        for i in range(len(results["ids"][0]))
        if passes_filters(results["metadatas"][0][i], language, path_prefix)
    ]
    return hits[:limit]


def keyword_search(query: str, limit: int, language: str | None, path_prefix: str | None) -> list[dict]:
    index = get_keyword_index()
    scores = index.bm25.get_scores(tokenize_for_keywords(query))
    ranked = sorted(range(len(scores)), key=scores.__getitem__, reverse=True)

    hits: list[dict] = []
    for i in ranked:
        if scores[i] <= 0 or len(hits) >= limit:
            break
        if passes_filters(index.metadatas[i], language, path_prefix):
            hits.append(
                {
                    "id": index.ids[i],
                    "content": index.documents[i],
                    "metadata": index.metadatas[i],
                    "distance": None,
                    "keyword_score": float(scores[i]),
                }
            )
    return hits


def symbol_search(query: str, limit: int, language: str | None, path_prefix: str | None) -> list[dict]:
    index = get_keyword_index()
    hits: list[dict] = []

    for symbol in dict.fromkeys(QUERY_SYMBOL.findall(query)):
        defining = sorted(
            index.definitions.get(symbol, []),
            key=lambda i: is_test_path(index.metadatas[i].get("path", "")),
        )
        for i in defining:
            if len(hits) >= limit:
                return hits
            if passes_filters(index.metadatas[i], language, path_prefix):
                hits.append(
                    {
                        "id": index.ids[i],
                        "content": index.documents[i],
                        "metadata": index.metadatas[i],
                        "distance": None,
                        "defines": symbol,
                    }
                )
    return hits


def reciprocal_rank_fusion(rankings: list[list[dict]], weights: list[float] | None = None) -> list[dict]:
    fused: dict[str, float] = {}
    by_id: dict[str, dict] = {}

    for ranking, weight in zip(rankings, weights or [1.0] * len(rankings), strict=True):
        for rank, hit in enumerate(ranking, start=1):
            fused[hit["id"]] = fused.get(hit["id"], 0.0) + weight / (RRF_K + rank)
            by_id[hit["id"]] = {**by_id.get(hit["id"], {}), **hit}

    ordered = sorted(fused, key=fused.__getitem__, reverse=True)
    return [{**by_id[i], "fusion_score": fused[i]} for i in ordered]


def is_test_path(path: str) -> bool:
    lowered = f"/{path.lower()}"
    return any(marker in lowered for marker in TEST_PATH_MARKERS)


def demote_test_files(query: str, hits: list[dict]) -> list[dict]:
    if TEST_PATH_PENALTY >= 1.0 or "test" in query.lower():
        return hits

    factor = {True: TEST_PATH_PENALTY, False: 1.0}
    adjusted = [
        {**h, "fusion_score": h["fusion_score"] * factor[is_test_path(h["metadata"].get("path", ""))]}
        for h in hits
    ]
    return sorted(adjusted, key=lambda h: h["fusion_score"], reverse=True)


def rerank(query: str, candidates: list[dict], top_k: int) -> list[dict]:
    if not candidates:
        return []

    scores = get_reranker().predict([(query, c["content"]) for c in candidates])
    scored = [{**c, "rerank_score": float(s)} for c, s in zip(candidates, scores, strict=True)]
    return sorted(scored, key=lambda c: c["rerank_score"], reverse=True)[:top_k]


def retrieve(
    query: str,
    top_k: int = 5,
    mode: Mode | None = None,
    language: str | None = None,
    path_prefix: str | None = None,
) -> list[dict]:
    mode = mode or RETRIEVAL_MODE
    pool = max(MIN_CANDIDATE_POOL, top_k * 4)
    started = time.perf_counter()

    if mode == "vector":
        results = vector_search(query, top_k, language, path_prefix)
    elif mode == "keyword":
        results = keyword_search(query, top_k, language, path_prefix)
    else:
        fused = demote_test_files(
            query,
            reciprocal_rank_fusion(
                [
                    vector_search(query, pool, language, path_prefix),
                    keyword_search(query, pool, language, path_prefix),
                    symbol_search(query, pool, language, path_prefix),
                ],
                [1.0, 1.0, SYMBOL_WEIGHT],
            ),
        )
        results = rerank(query, fused[:pool], top_k) if mode == "hybrid_rerank" else fused[:top_k]

    logger.info(
        "retrieve mode=%s top_k=%d filters=%s/%s ms=%.0f query=%r ids=%s",
        mode,
        top_k,
        language,
        path_prefix,
        (time.perf_counter() - started) * 1000,
        query,
        [r["id"] for r in results],
    )
    return results
