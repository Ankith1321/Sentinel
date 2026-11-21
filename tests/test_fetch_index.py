import pytest

from ingestion import fetch_index


def make_index(path):
    path.mkdir(parents=True)
    (path / "chroma.sqlite3").write_bytes(b"x")


def test_an_existing_index_is_not_downloaded_again(tmp_path, monkeypatch):
    make_index(tmp_path / "chroma")
    monkeypatch.setattr(fetch_index, "snapshot_download", lambda **kw: pytest.fail("must not download"))

    assert fetch_index.fetch_index("someone/index", str(tmp_path / "chroma")) is False


def test_a_missing_index_is_downloaded_from_the_dataset(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(fetch_index, "snapshot_download", lambda **kw: calls.append(kw))

    assert fetch_index.fetch_index("someone/index", str(tmp_path / "chroma")) is True
    assert calls == [{"repo_id": "someone/index", "repo_type": "dataset", "local_dir": str(tmp_path / "chroma")}]


def test_a_missing_index_without_a_repo_is_a_clear_error(tmp_path):
    with pytest.raises(SystemExit, match="SENTINEL_INDEX_REPO"):
        fetch_index.fetch_index("", str(tmp_path / "chroma"))


def test_publishing_creates_the_dataset_and_uploads_the_folder(tmp_path, monkeypatch):
    make_index(tmp_path / "chroma")
    calls = []

    class FakeApi:
        def create_repo(self, **kw):
            calls.append(("create_repo", kw))

        def upload_folder(self, **kw):
            calls.append(("upload_folder", kw))

    monkeypatch.setattr(fetch_index, "HfApi", FakeApi)
    fetch_index.publish_index("someone/index", str(tmp_path / "chroma"))

    assert [name for name, _ in calls] == ["create_repo", "upload_folder"]
    assert calls[1][1] == {"repo_id": "someone/index", "repo_type": "dataset", "folder_path": str(tmp_path / "chroma")}


def test_publishing_without_an_index_is_refused(tmp_path):
    with pytest.raises(SystemExit, match="No index"):
        fetch_index.publish_index("someone/index", str(tmp_path / "missing"))
