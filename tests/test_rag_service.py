import re
from types import SimpleNamespace

import pytest

from ingestion import llm, rag_service


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, reply: str = "Answer from cache.py [S1].") -> None:
        self.reply = reply
        self.calls: list[dict] = []

    def complete(self, system, messages, max_tokens):
        self.calls.append({"system": system, "messages": messages, "max_tokens": max_tokens})
        return self.reply

    def stream(self, system, messages, max_tokens):
        yield from re.findall(r"\S+\s*", self.reply)


def context(chunk_id: str, text: str = "def generate_cache_key(): pass", path: str = "superset/utils/cache.py") -> dict:
    metadata = {"path": path, "language": "python", "title": "cache.py"}
    return {"id": chunk_id, "content": text, "metadata": metadata, "distance": 0.3}


@pytest.fixture()
def provider(monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr(rag_service, "get_provider", lambda: fake)
    return fake


def test_messages_number_passages_and_keep_history_first(monkeypatch):
    monkeypatch.setattr(rag_service, "PROMPT_VARIANT", "v1")
    history = [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "reply"}]

    messages = rag_service.build_messages("what next?", [context("a"), context("b")], history)

    assert messages[:2] == history
    assert messages[-1]["role"] == "user"
    assert "[S1]" in messages[-1]["content"] and "[S2]" in messages[-1]["content"]
    assert messages[-1]["content"].endswith("QUESTION: what next?")


def test_strict_prompt_repeats_the_rules_after_the_question(monkeypatch):
    monkeypatch.setattr(rag_service, "PROMPT_VARIANT", "v2")

    last = rag_service.build_messages("where is x?", [context("a")], [])[-1]["content"]

    assert last.index("QUESTION: where is x?") < last.index("Reminder: answer in 2 to 5 sentences")


def test_context_budget_drops_the_least_relevant_whole_chunks():
    contexts = [context(str(i), "word " * 60) for i in range(10)]

    kept = rag_service.fit_contexts_to_budget(contexts, budget=150)

    assert 1 <= len(kept) < 10
    assert [c["id"] for c in kept] == [str(i) for i in range(len(kept))]
    assert all(c["content"] == "word " * 60 for c in kept)


def test_context_budget_always_keeps_the_best_chunk():
    assert len(rag_service.fit_contexts_to_budget([context("a", "word " * 500)], budget=10)) == 1


def test_first_question_is_not_rewritten(provider):
    assert rag_service.reformulate_question("how does caching work", []) == "how does caching work"
    assert provider.calls == []


def test_follow_up_is_rewritten_with_history(provider):
    provider.reply = "What methods does BaseDAO provide for querying?\nextra line"
    history = [
        {"role": "user", "content": "What does BaseDAO do?"},
        {"role": "assistant", "content": "It wraps queries"},
    ]

    rewritten = rag_service.reformulate_question("which methods does it have?", history)

    assert rewritten == "What methods does BaseDAO provide for querying?"
    assert "BaseDAO" in provider.calls[0]["messages"][0]["content"]


def test_rewrite_failure_falls_back_to_the_original_question(monkeypatch):
    class Broken(FakeProvider):
        def complete(self, *args):
            raise RuntimeError("api down")

    monkeypatch.setattr(rag_service, "get_provider", lambda: Broken())

    assert rag_service.reformulate_question("and then?", [{"role": "user", "content": "x"}]) == "and then?"


def test_ask_returns_answer_sources_and_timings(monkeypatch, provider):
    monkeypatch.setattr(rag_service, "retrieve", lambda *a, **k: [context("a"), context("b", path="docs/x.md")])

    result = rag_service.ask_sentinel("where is the cache key built?", top_k=2)

    assert result["answer"] == "Answer from cache.py [S1]."
    assert [s["id"] for s in result["sources"]] == ["S1", "S2"]
    assert result["sources"][1]["path"] == "docs/x.md"
    assert result["model"] == "fake-model"
    assert {"retrieval_ms", "generation_ms"} <= set(result)
    assert provider.calls[0]["max_tokens"] == rag_service.MAX_ANSWER_TOKENS


def test_stream_emits_sources_then_tokens_then_done(monkeypatch, provider):
    monkeypatch.setattr(rag_service, "retrieve", lambda *a, **k: [context("a")])

    events = list(rag_service.stream_sentinel("where is the cache key built?"))

    assert [name for name, _ in events] == ["sources", "token", "token", "token", "token", "done"]
    assert events[-1][1]["answer"] == "Answer from cache.py [S1]."


def test_anthropic_provider_joins_text_blocks_and_reports_refusals(monkeypatch):
    calls = []

    class FakeMessages:
        def __init__(self, stop_reason):
            self.stop_reason = stop_reason

        def create(self, **kwargs):
            calls.append(kwargs)
            blocks = [SimpleNamespace(type="thinking", text=None), SimpleNamespace(type="text", text="Hello [S1]")]
            return SimpleNamespace(content=blocks, stop_reason=self.stop_reason)

    for stop_reason, expected in [("end_turn", "Hello [S1]"), ("refusal", llm.REFUSAL_NOTICE)]:
        fake_client = SimpleNamespace(messages=FakeMessages(stop_reason))
        monkeypatch.setattr(llm.anthropic, "Anthropic", lambda client=fake_client: client)
        provider = llm.AnthropicProvider("claude-haiku-5-5")

        assert provider.complete("system", [{"role": "user", "content": "hi"}], 100) == expected

    assert calls[0]["model"] == "claude-haiku-5-5" and calls[0]["system"] == "system" and calls[0]["max_tokens"] == 100


def test_provider_choice_follows_the_api_key(monkeypatch):
    monkeypatch.setattr(llm, "LLM_PROVIDER", "auto")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert llm.resolve_provider_name() == "anthropic"

    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert llm.resolve_provider_name() == "local"

    monkeypatch.setattr(llm, "LLM_PROVIDER", "local")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert llm.resolve_provider_name() == "local"
