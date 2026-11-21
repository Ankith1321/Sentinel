import json
import re
from types import SimpleNamespace

import httpx
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


def test_provider_choice_follows_the_key_and_the_hardware(monkeypatch):
    monkeypatch.setattr(llm, "LLM_PROVIDER", "auto")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("SENTINEL_OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(llm.torch.cuda, "is_available", lambda: False)
    assert llm.resolve_provider_name() == "none"

    monkeypatch.setattr(llm.torch.cuda, "is_available", lambda: True)
    assert llm.resolve_provider_name() == "local"

    monkeypatch.setattr(llm, "OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setattr(llm, "OPENAI_MODEL", "some-free-model")
    monkeypatch.setenv("SENTINEL_OPENAI_API_KEY", "free-key")
    assert llm.resolve_provider_name() == "openai"

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert llm.resolve_provider_name() == "anthropic"

    monkeypatch.setattr(llm, "LLM_PROVIDER", "local")
    assert llm.resolve_provider_name() == "local"


def test_secrets_in_passages_never_reach_the_model_or_the_source_previews(monkeypatch, provider):
    leaky = context("a", text='SECRET_KEY = "CHANGE_ME_TO_A_COMPLEX_RANDOM_SECRET"\ndef load(): pass')
    monkeypatch.setattr(rag_service, "retrieve", lambda *a, **k: [leaky])

    result = rag_service.ask_sentinel("how is the secret key configured?")
    prompt = provider.calls[0]["messages"][-1]["content"]

    assert "CHANGE_ME" not in prompt and 'SECRET_KEY = "[REDACTED]"' in prompt
    assert "CHANGE_ME" not in result["sources"][0]["preview"]


def test_secret_shaped_text_is_redacted_from_the_answer(monkeypatch):
    fake = FakeProvider(reply="The key is " + "sk-ant-" + "x" * 30 + " [S1].")
    monkeypatch.setattr(rag_service, "get_provider", lambda: fake)
    monkeypatch.setattr(rag_service, "retrieve", lambda *a, **k: [context("a")])

    result = rag_service.ask_sentinel("what is the key?")

    assert "sk-ant" not in result["answer"] and "[REDACTED API KEY]" in result["answer"]


@pytest.fixture()
def no_model(monkeypatch):
    monkeypatch.setattr(rag_service, "get_provider", lambda: None)
    passages = [
        context("a", text="File: superset/utils/cache.py\ndef generate_cache_key(): pass"),
        context("b", text="File: docs/x.md\n# Caching", path="docs/x.md"),
    ]
    monkeypatch.setattr(rag_service, "retrieve", lambda *a, **k: passages)


def test_without_a_model_the_answer_lists_the_closest_passages(no_model):
    result = rag_service.ask_sentinel("where is the cache key built?", top_k=2)

    assert result["model"] == rag_service.RETRIEVAL_ONLY_MODEL and result["generation_ms"] == 0
    assert "`superset/utils/cache.py` [S1]" in result["answer"] and "`docs/x.md` [S2]" in result["answer"]
    assert [s["id"] for s in result["sources"]] == ["S1", "S2"]
    assert result["checks"]["needs_review"] is False


def test_without_a_model_the_stream_still_sends_sources_then_the_answer(no_model):
    events = list(rag_service.stream_sentinel("where is the cache key built?", top_k=2))

    assert [name for name, _ in events] == ["sources", "token", "done"]
    assert events[-1][1]["model"] == rag_service.RETRIEVAL_ONLY_MODEL
    assert "[S1]" in events[-1][1]["answer"]


def test_without_a_model_a_follow_up_is_not_rewritten(monkeypatch):
    monkeypatch.setattr(rag_service, "get_provider", lambda: None)

    assert rag_service.reformulate_question("and where is it used?", [{"role": "user", "content": "x"}]) == (
        "and where is it used?"
    )


def openai_provider(handler):
    transport = httpx.MockTransport(handler)
    return llm.OpenAICompatibleProvider("some-free-model", "https://example.test/v1/", "free-key", transport)


def test_openai_compatible_provider_sends_the_prompt_and_reads_the_reply():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(request.url), request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": " Answer [S1]. "}}]})

    reply = openai_provider(handler).complete("system text", [{"role": "user", "content": "hi"}], 100)

    assert reply == "Answer [S1]."
    assert seen["url"] == "https://example.test/v1/chat/completions" and seen["auth"] == "Bearer free-key"
    assert seen["body"]["model"] == "some-free-model" and seen["body"]["max_tokens"] == 100
    assert seen["body"]["messages"][0] == {"role": "system", "content": "system text"}


def test_openai_compatible_provider_streams_the_deltas_until_done():
    sse = (
        'data: {"choices": [{"delta": {"role": "assistant"}}]}\n\n'
        'data: {"choices": [{"delta": {"content": "Cache "}}]}\n\n'
        'data: {"choices": [{"delta": {"content": "keys [S1]."}}]}\n\n'
        "data: [DONE]\n\n"
    )
    provider = openai_provider(lambda request: httpx.Response(200, text=sse))

    assert "".join(provider.stream("system", [{"role": "user", "content": "hi"}], 100)) == "Cache keys [S1]."
