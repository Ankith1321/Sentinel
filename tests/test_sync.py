import pytest

from backend.app import documents, store, sync
from backend.app.db import connect, init_db


class FakeCollection:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def get(self, where=None, include=None):
        ids = [i for i, meta in self.rows.items() if not where or all(meta.get(k) == v for k, v in where.items())]
        return {"ids": ids}

    def delete(self, ids):
        for chunk_id in ids:
            self.rows.pop(chunk_id, None)

    def upsert_chunks(self, chunks) -> None:
        for c in chunks:
            self.rows[c.chunk_id] = {"source_id": c.source_id, "path": c.path}

    def paths(self) -> set[str]:
        return {meta["path"] for meta in self.rows.values()}


def function_source(count: int) -> str:
    return "\n\n".join(
        f'def compute_total_{i}(rows):\n    """Add up the revenue column of report {i} and return it."""\n'
        f"    total = 0\n    for row in rows:\n        total += row['revenue_{i}'] * {i}\n    return total"
        for i in range(count)
    )


@pytest.fixture()
def corpus(tmp_path, monkeypatch):
    init_db()
    with connect() as db:
        db.execute("DELETE FROM documents")
    fake = FakeCollection()
    refreshes: list[int] = []
    monkeypatch.setattr(sync, "get_collection", lambda: fake)
    monkeypatch.setattr(documents, "get_collection", lambda: fake)
    monkeypatch.setattr(documents, "embed_and_upsert", fake.upsert_chunks)
    monkeypatch.setattr(sync, "refresh_keyword_index", lambda: refreshes.append(1))
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "reports.py").write_text(function_source(12), encoding="utf-8")
    (tmp_path / "guide.md").write_text(
        "# Running reports\n\nReports are computed nightly by the scheduler and stored for thirty days "
        "so that analysts can compare revenue across regions without recomputing anything.\n",
        encoding="utf-8",
    )
    return tmp_path, fake, refreshes


def test_first_sync_indexes_everything_and_a_second_sync_changes_nothing(corpus):
    root, fake, refreshes = corpus

    first = sync.sync_corpus(root)
    second = sync.sync_corpus(root)

    assert (first.added, first.changed, first.removed) == (2, 0, 0)
    assert fake.paths() == {"pkg/reports.py", "guide.md"}
    assert (second.added, second.changed, second.removed, second.unchanged) == (0, 0, 0, 2)
    assert len(refreshes) == 1


def test_a_changed_file_is_reindexed_and_its_old_chunks_are_removed(corpus):
    root, fake, _ = corpus
    sync.sync_corpus(root)
    before = sum(1 for m in fake.rows.values() if m["path"] == "pkg/reports.py")

    (root / "pkg" / "reports.py").write_text(function_source(1), encoding="utf-8")
    report = sync.sync_corpus(root)

    after = sum(1 for m in fake.rows.values() if m["path"] == "pkg/reports.py")
    assert report.changed == 1 and report.chunks_deleted == before - after
    assert before > after >= 1
    assert store.corpus_documents()["pkg/reports.py"]["chunk_count"] == after


def test_a_deleted_file_disappears_from_the_index_and_the_manifest(corpus):
    root, fake, _ = corpus
    sync.sync_corpus(root)

    (root / "guide.md").unlink()
    report = sync.sync_corpus(root)

    assert report.removed == 1
    assert fake.paths() == {"pkg/reports.py"}
    assert "guide.md" not in store.corpus_documents()


def test_uploaded_documents_are_never_touched(corpus):
    root, fake, _ = corpus
    store.upsert_document("upload-1", "uploads/notes.md", "upload", "markdown", "hash", 1)
    fake.rows["upload-1::chunk_0"] = {"source_id": "upload-1", "path": "uploads/notes.md"}

    sync.sync_corpus(root)

    assert "upload-1::chunk_0" in fake.rows
    assert store.get_document("upload-1") is not None


def test_a_file_that_fails_is_reported_and_not_deleted(corpus, monkeypatch):
    root, fake, _ = corpus
    sync.sync_corpus(root)
    changed = "# Changed\n\n" + "A changed paragraph about nightly reports. " * 10
    (root / "guide.md").write_text(changed, encoding="utf-8")
    real_chunk_record = sync.chunk_record

    def flaky(record):
        if record.path == "guide.md":
            raise RuntimeError("tokenizer exploded")
        return real_chunk_record(record)

    monkeypatch.setattr(sync, "chunk_record", flaky)
    report = sync.sync_corpus(root)

    assert report.removed == 0 and len(report.errors) == 1 and "guide.md" in report.errors[0]
    assert "guide.md" in store.corpus_documents()
    assert "guide.md" in fake.paths()


def test_a_second_sync_is_refused_while_one_is_running(corpus):
    root, _, _ = corpus
    sync._sync_lock.acquire()
    try:
        with pytest.raises(sync.SyncInProgress):
            sync.sync_corpus(root)
    finally:
        sync._sync_lock.release()
