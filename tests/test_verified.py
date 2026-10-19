import hashlib
import re

import numpy as np
import pytest

from backend.app import store, verified
from backend.app.db import connect, init_db

DIMENSIONS = 256
SOURCES = [{"id": "S1", "path": "superset/utils/cache_manager.py", "preview": "class CacheManager: ..."}]


def fake_embed(texts: list[str]) -> np.ndarray:
    vectors = np.zeros((len(texts), DIMENSIONS), dtype=np.float32)
    for row, text in enumerate(texts):
        for word in re.findall(r"[a-z_]+", text.lower()):
            vectors[row, int(hashlib.md5(word.encode()).hexdigest(), 16) % DIMENSIONS] += 1.0
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.where(norms == 0, 1, norms)


@pytest.fixture(autouse=True)
def clean_store(monkeypatch):
    init_db()
    with connect() as db:
        db.execute("DELETE FROM verified_answers")
        db.execute("DELETE FROM documents")
    monkeypatch.setattr(verified, "embed", fake_embed)
    verified.invalidate()
    store.upsert_document("doc-cache", "superset/utils/cache_manager.py", "code", "python", "hash-v1", 3)
    yield
    verified.invalidate()


def approved(question: str, answer: str = "Caches are configured in CacheManager [S1].") -> int:
    answer_id = store.create_verified_answer(question, answer, SOURCES, "generated")
    verified.approve(answer_id)
    return answer_id


def test_approval_requires_a_valid_citation():
    uncited = store.create_verified_answer("How are caches set up?", "Caches are set up at startup.", SOURCES, "chat")
    bad_ref = store.create_verified_answer("How are caches cleared?", "Via the manager [S4].", SOURCES, "chat")

    with pytest.raises(verified.ApprovalRejected):
        verified.approve(uncited)
    with pytest.raises(verified.ApprovalRejected):
        verified.approve(bad_ref)

    verified.approve(uncited, "Caches are set up by CacheManager at startup [S1].")
    row = store.get_verified_answer(uncited)
    assert row["status"] == "approved"
    assert '"superset/utils/cache_manager.py": "hash-v1"' in row["source_hashes_json"]


def test_the_same_question_is_served_and_a_different_one_is_not():
    answer_id = approved("How does Superset set up and configure its caches?")

    hit = verified.find_match("How does Superset set up and configure its caches?")
    miss = verified.find_match("Where are the dashboard REST endpoints defined?")

    assert hit is not None and hit.id == answer_id and hit.similarity > 0.99
    assert hit.sources[0]["path"] == "superset/utils/cache_manager.py"
    assert miss is None


def test_pending_and_rejected_answers_are_never_served():
    store.create_verified_answer("How does Superset configure caches?", "CacheManager [S1].", SOURCES, "generated")
    rejected = approved("How are caches configured in Superset?")
    verified.set_status(rejected, "rejected")

    assert verified.find_match("How does Superset configure caches?", threshold=0.0) is None


def test_a_code_name_in_the_question_must_appear_in_the_stored_question():
    approved("Where is get_since_until defined?", "It is defined in the date parser [S1].")

    assert verified.find_match("Where is get_until defined?", threshold=0.0) is None
    assert verified.find_match("Where is get_since_until defined?") is not None


def test_an_answer_whose_source_changed_goes_stale_instead_of_being_served():
    answer_id = approved("How does Superset set up and configure its caches?")
    store.upsert_document("doc-cache", "superset/utils/cache_manager.py", "code", "python", "hash-v2", 3)

    assert verified.find_match("How does Superset set up and configure its caches?") is None
    row = store.get_verified_answer(answer_id)
    assert row["status"] == "stale" and "cache_manager.py" in row["stale_reason"]


def test_a_sync_that_touches_a_source_marks_the_answer_stale():
    answer_id = approved("How does Superset set up and configure its caches?")

    assert verified.mark_stale({"superset/app.py"}) == 0
    assert verified.mark_stale({"superset/utils/cache_manager.py"}) == 1
    assert store.get_verified_answer(answer_id)["status"] == "stale"
    assert verified.find_match("How does Superset set up and configure its caches?") is None


def test_the_same_question_cannot_be_queued_twice():
    first = store.create_verified_answer("How are caches set up?", "x [S1]", SOURCES, "chat")

    assert first is not None
    assert store.create_verified_answer("how are caches set up?", "y [S1]", SOURCES, "generated") is None
