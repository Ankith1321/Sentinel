import json
from pathlib import Path

import pytest

from ingestion.guardrails import injection_reason, redact, sentence_support

CASES = json.loads((Path(__file__).resolve().parents[1] / "eval" / "guardrail_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("question", CASES["injection"])
def test_injection_attempts_are_blocked(question):
    assert injection_reason(question) == "prompt_injection"


@pytest.mark.parametrize("question", CASES["benign"])
def test_look_alike_codebase_questions_are_not_blocked(question):
    assert injection_reason(question) is None


def test_secrets_are_redacted_and_counted():
    text = (
        'SECRET_KEY = "CHANGE_ME_TO_A_COMPLEX_RANDOM_SECRET"\n'
        f"aws = {'AKIA' + 'X' * 16}\n"
        f"anthropic = {'sk-' + 'ant-api03-' + 'x' * 32}\n"
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----\n"
        "password: 'short'\n"
    )

    cleaned, count = redact(text)

    assert count == 4
    assert "CHANGE_ME" not in cleaned and 'SECRET_KEY = "[REDACTED]"' in cleaned
    assert "AKIA" not in cleaned and "sk-ant" not in cleaned and "MIIEow" not in cleaned
    assert "password: 'short'" in cleaned


def test_text_without_secrets_is_untouched():
    text = "def get_since_until(time_range): return parse(time_range)"

    assert redact(text) == (text, 0)


def test_supported_sentences_score_high_and_invented_ones_low():
    passages = ["class CacheManager: configures the data cache, thumbnail cache and filter state cache with Redis."]
    grounded = "CacheManager configures the data cache and the thumbnail cache [S1]."
    invented = "CacheManager configures the data cache [S1]. Kubernetes operators rebalance Cassandra shards nightly."

    assert sentence_support(grounded, passages).ratio == 1.0
    weak = sentence_support(invented, passages)
    assert weak.ratio == 0.5 and weak.unsupported == ["Kubernetes operators rebalance Cassandra shards nightly."]
