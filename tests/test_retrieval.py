from ingestion import retriever
from ingestion.retriever import (
    demote_test_files,
    is_test_path,
    passes_filters,
    reciprocal_rank_fusion,
    tokenize_for_keywords,
)


def hit(chunk_id: str, path: str = "superset/app.py", **extra) -> dict:
    return {"id": chunk_id, "content": chunk_id, "metadata": {"path": path, "language": "python"}, **extra}


def test_tokenizer_keeps_identifiers_and_splits_their_parts():
    tokens = tokenize_for_keywords("SupersetSecurityException get_since_until")

    assert "supersetsecurityexception" in tokens
    assert {"superset", "security", "exception"} <= set(tokens)
    assert {"get", "since", "until", "get_since_until"} <= set(tokens)


def test_fusion_rewards_chunks_found_by_both_searches():
    vector = [hit("a"), hit("b"), hit("c")]
    keyword = [hit("c"), hit("d")]

    fused = reciprocal_rank_fusion([vector, keyword])

    assert fused[0]["id"] == "c" or fused[0]["id"] == "a"
    assert {h["id"] for h in fused} == {"a", "b", "c", "d"}
    scores = {h["id"]: h["fusion_score"] for h in fused}
    assert scores["c"] > scores["b"] and scores["c"] > scores["d"]


def test_fusion_keeps_fields_from_both_rankings():
    fused = reciprocal_rank_fusion([[hit("a", distance=0.2)], [hit("a", keyword_score=7.0)]])

    assert fused[0]["distance"] == 0.2 and fused[0]["keyword_score"] == 7.0


def test_test_paths_are_recognised():
    assert is_test_path("tests/unit_tests/utils/date_parser_tests.py")
    assert is_test_path("superset-frontend/src/theme/ThemeController.test.ts")
    assert is_test_path("superset-frontend/plugins/x/src/stories/Handlebars.stories.tsx")
    assert not is_test_path("superset/utils/date_parser.py")


def test_test_files_are_demoted_unless_the_query_asks_for_tests(monkeypatch):
    monkeypatch.setattr(retriever, "TEST_PATH_PENALTY", 0.5)
    hits = [
        hit("test", "tests/unit_tests/x_tests.py", fusion_score=0.030),
        hit("real", "superset/x.py", fusion_score=0.020),
    ]

    assert [h["id"] for h in demote_test_files("where is x defined", hits)] == ["real", "test"]
    assert [h["id"] for h in demote_test_files("how are the x tests written", hits)] == ["test", "real"]


def test_demotion_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(retriever, "TEST_PATH_PENALTY", 1.0)
    hits = [hit("test", "tests/x_tests.py", fusion_score=0.03), hit("real", "superset/x.py", fusion_score=0.02)]

    assert demote_test_files("where is x", hits) == hits


def test_filters_match_language_and_path_prefix():
    meta = {"language": "python", "path": "superset/utils/cache.py"}

    assert passes_filters(meta, None, None)
    assert passes_filters(meta, "python", "superset/utils")
    assert not passes_filters(meta, "typescript", None)
    assert not passes_filters(meta, None, "docs/")
