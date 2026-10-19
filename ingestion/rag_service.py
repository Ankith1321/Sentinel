import json
import logging
import time
from collections.abc import Iterator

from ingestion.answer_checks import check_answer
from ingestion.chunker import count_tokens
from ingestion.config import CONTEXT_TOKEN_BUDGET, MAX_ANSWER_TOKENS, PROMPT_VARIANT
from ingestion.llm import get_provider
from ingestion.retriever import retrieve

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Sentinel, an assistant for engineers working in the Apache Superset codebase.

Answer using ONLY the numbered passages supplied with the question. They are the only source of truth.

Rules:
- Cite every factual claim with its passage marker, for example [S1] or [S2][S3].
- If the passages do not contain the answer, say so plainly and name what is missing.
  Do not guess and do not use outside knowledge.
- If a passage supports a point only partly, say it is only partially supported.
- Prefer concrete file paths, class names and function names taken from the passages.
- Cite a passage only when it directly supports the sentence.
- Markers like [S1] in earlier conversation turns refer to those turns' own passages, not the current ones.

Format: a direct answer first, then a short "Relevant files" list."""

STRICT_SYSTEM_PROMPT = """You answer questions about the Apache Superset codebase using ONLY the numbered passages given with each question.

How to answer:
1. Write 2 to 5 short sentences. After every sentence that states a fact, add the number of the passage it came from, like [S1] or [S2].
2. Name the exact file paths, classes and functions that appear in the passages. Never mention a file, class or function that is not in the passages.
3. If the passages do not answer the question, reply: "The retrieved passages do not contain the answer." Then say in one sentence what is missing.
4. Do not write code unless a passage contains that exact code.

Example of the format only (not about Superset):
Question: Where is the retry limit set?
Answer: The retry limit is read from the `RETRY_MAX` setting in `config.py` [S1]. The worker applies it when it schedules a task [S2]."""

SYSTEM_PROMPTS = {"v1": SYSTEM_PROMPT, "v2": STRICT_SYSTEM_PROMPT}
REMINDERS = {
    "v1": "",
    "v2": "\n\nReminder: answer in 2 to 5 sentences, cite every fact as [S#], and use only the passages above.",
}

REFORMULATE_SYSTEM_PROMPT = """You rewrite a follow-up question into a standalone search query for a code search engine.
Use the conversation to resolve pronouns and references. Keep identifiers, file names and technical terms exactly.
Output only the rewritten query on one line, with no quotes and no explanation."""

REFORMULATE_MAX_TOKENS = 80
SNIPPET_CHARS = 500


def fit_contexts_to_budget(contexts: list[dict], budget: int) -> list[dict]:
    kept: list[dict] = []
    used = 0

    for context in contexts:
        tokens = count_tokens(context["content"])
        if kept and used + tokens > budget:
            break
        kept.append(context)
        used += tokens

    return kept


def reformulate_question(question: str, history: list[dict]) -> str:
    if not history:
        return question

    transcript = "\n".join(f"{turn['role']}: {turn['content'][:600]}" for turn in history[-6:])
    prompt = f"Conversation so far:\n{transcript}\n\nFollow-up question: {question}\n\nStandalone query:"

    try:
        rewritten = get_provider().complete(
            REFORMULATE_SYSTEM_PROMPT,
            [{"role": "user", "content": prompt}],
            REFORMULATE_MAX_TOKENS,
        )
    except Exception:
        logger.exception("query reformulation failed; using the original question")
        return question

    lines = [line.strip() for line in rewritten.splitlines() if line.strip()]
    return lines[0] if lines else question


def format_context_block(index: int, context: dict) -> str:
    meta = context["metadata"]
    return (
        f"[S{index}]\n"
        f"Path: {meta.get('path')}\n"
        f"Language: {meta.get('language')}\n"
        f"Content:\n{context['content']}\n"
    )


def build_messages(question: str, contexts: list[dict], history: list[dict]) -> list[dict]:
    blocks = "\n\n".join(format_context_block(i, c) for i, c in enumerate(contexts, start=1))
    current = (
        "Passages for the current question (markers [S1], [S2], ... refer only to these):\n\n"
        f"{blocks}\n\nQUESTION: {question}{REMINDERS[PROMPT_VARIANT]}"
    )
    return [*history, {"role": "user", "content": current}]


def build_sources(contexts: list[dict]) -> list[dict]:
    return [
        {
            "id": f"S{i}",
            "path": c["metadata"].get("path"),
            "language": c["metadata"].get("language"),
            "title": c["metadata"].get("title"),
            "distance": c.get("distance"),
            "score": c.get("rerank_score", c.get("fusion_score", c.get("keyword_score"))),
            "preview": c["content"][:SNIPPET_CHARS],
        }
        for i, c in enumerate(contexts, start=1)
    ]


def prepare(
    question: str,
    top_k: int,
    history: list[dict] | None,
    mode: str | None,
    language: str | None,
    path_prefix: str | None,
) -> dict:
    history = history or []
    standalone = reformulate_question(question, history)

    started = time.perf_counter()
    retrieved = retrieve(standalone, top_k=top_k, mode=mode, language=language, path_prefix=path_prefix)
    contexts = fit_contexts_to_budget(retrieved, CONTEXT_TOKEN_BUDGET)
    retrieval_ms = (time.perf_counter() - started) * 1000

    return {
        "standalone_question": standalone,
        "contexts": contexts,
        "sources": build_sources(contexts),
        "messages": build_messages(standalone, contexts, history),
        "retrieval_ms": retrieval_ms,
    }


def log_query(question: str, prepared: dict, generation_ms: float, model: str) -> None:
    logger.info(
        "query_log %s",
        json.dumps(
            {
                "question": question,
                "standalone_question": prepared["standalone_question"],
                "retrieved_ids": [c["id"] for c in prepared["contexts"]],
                "retrieval_ms": round(prepared["retrieval_ms"]),
                "generation_ms": round(generation_ms),
                "model": model,
            }
        ),
    )


def ask_sentinel(
    question: str,
    top_k: int = 5,
    history: list[dict] | None = None,
    mode: str | None = None,
    language: str | None = None,
    path_prefix: str | None = None,
) -> dict:
    prepared = prepare(question, top_k, history, mode, language, path_prefix)
    provider = get_provider()

    started = time.perf_counter()
    answer = provider.complete(SYSTEM_PROMPTS[PROMPT_VARIANT], prepared["messages"], MAX_ANSWER_TOKENS)
    generation_ms = (time.perf_counter() - started) * 1000

    log_query(question, prepared, generation_ms, provider.model)

    return {
        "question": question,
        "standalone_question": prepared["standalone_question"],
        "answer": answer,
        "sources": prepared["sources"],
        "top_k": top_k,
        "model": provider.model,
        "retrieval_ms": round(prepared["retrieval_ms"]),
        "generation_ms": round(generation_ms),
        "retrieved_ids": [c["id"] for c in prepared["contexts"]],
        "checks": check_answer(answer, prepared["contexts"]).to_dict(),
    }


def stream_sentinel(
    question: str,
    top_k: int = 5,
    history: list[dict] | None = None,
    mode: str | None = None,
    language: str | None = None,
    path_prefix: str | None = None,
) -> Iterator[tuple[str, object]]:
    prepared = prepare(question, top_k, history, mode, language, path_prefix)
    provider = get_provider()

    yield "sources", {"sources": prepared["sources"], "standalone_question": prepared["standalone_question"]}

    started = time.perf_counter()
    parts: list[str] = []
    for token in provider.stream(SYSTEM_PROMPTS[PROMPT_VARIANT], prepared["messages"], MAX_ANSWER_TOKENS):
        parts.append(token)
        yield "token", token

    generation_ms = (time.perf_counter() - started) * 1000
    log_query(question, prepared, generation_ms, provider.model)

    answer = "".join(parts).strip()
    yield "done", {
        "answer": answer,
        "checks": check_answer(answer, prepared["contexts"]).to_dict(),
        "sources": prepared["sources"],
        "model": provider.model,
        "retrieval_ms": round(prepared["retrieval_ms"]),
        "generation_ms": round(generation_ms),
        "retrieved_ids": [c["id"] for c in prepared["contexts"]],
        "standalone_question": prepared["standalone_question"],
    }
