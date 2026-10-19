from ingestion.answer_checks import check_answer, mentioned_terms


def passage(text: str) -> dict:
    return {"content": text}


CONTEXTS = [
    passage("File: superset/utils/cache_manager.py\nclass CacheManager:\n    def init_app(self): ..."),
    passage("File: superset/utils/cache.py\ndef generate_cache_key(values): ..."),
]


def test_valid_citations_and_known_names_need_no_review():
    answer = (
        "`CacheManager` in `superset/utils/cache_manager.py` sets up caches [S1]. "
        "Keys come from `generate_cache_key()` [S2]."
    )

    checks = check_answer(answer, CONTEXTS)

    assert checks.cited_sources == [1, 2]
    assert checks.unsupported_terms == []
    assert not checks.needs_review


def test_answer_without_citations_is_flagged():
    checks = check_answer("The cache manager sets up caches.", CONTEXTS)

    assert checks.cited_sources == []
    assert checks.needs_review


def test_citation_to_a_passage_that_was_not_retrieved_is_flagged():
    checks = check_answer("It is defined in the manager [S1] and also [S7].", CONTEXTS)

    assert checks.cited_sources == [1]
    assert checks.invalid_citations == [7]
    assert checks.needs_review


def test_names_missing_from_the_passages_are_reported_as_unsupported():
    checks = check_answer("`CacheManager` [S1] uses `RedisSentinelCacheBackend` [S1].", CONTEXTS)

    assert checks.unsupported_terms == ["RedisSentinelCacheBackend"]
    assert checks.needs_review


def test_an_honest_refusal_is_not_flagged():
    refusal = "The retrieved passages do not contain the answer. The checkout steps are missing."
    checks = check_answer(refusal, CONTEXTS)

    assert checks.abstained
    assert not checks.needs_review


def test_code_snippets_in_backticks_are_not_treated_as_names():
    assert mentioned_terms("Use `x = compute(1, 2)` or `generate_cache_key()` or `a/b/c.py`.") == {
        "generate_cache_key",
        "a/b/c.py",
    }


def test_grouped_citations_are_recognised():
    checks = check_answer("Caches are set up in the manager [S1, S2] and keys elsewhere [S1; S2].", CONTEXTS)

    assert checks.cited_sources == [1, 2]
    assert not checks.invalid_citations


def test_not_directly_described_counts_as_a_refusal():
    assert check_answer("The chart model is not directly described in the passages.", CONTEXTS).abstained
