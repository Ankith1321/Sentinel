from eval.run_eval import first_hit_rank, summarise


def test_first_hit_rank_returns_position_of_earliest_expected_path():
    retrieved = ["a.py", "b.py", "target.py", "target.py"]

    assert first_hit_rank(retrieved, ["target.py"]) == 3


def test_first_hit_rank_is_none_when_nothing_matches():
    assert first_hit_rank(["a.py", "b.py"], ["target.py"]) is None


def test_summary_computes_hit_rates_and_mrr():
    rows = [
        {"type": "code", "rank": 1},
        {"type": "code", "rank": 4},
        {"type": "docs", "rank": None},
        {"type": "docs", "rank": 8},
    ]

    overall = summarise(rows)["overall"]

    assert overall["n"] == 4
    assert overall["hit@1"] == 0.25
    assert overall["hit@5"] == 0.5
    assert overall["hit@10"] == 0.75
    assert overall["mrr"] == round((1 + 0.25 + 0 + 0.125) / 4, 4)
