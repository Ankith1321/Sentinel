import json

import pytest
from fastapi.testclient import TestClient

from backend.app import main, store

ADMIN = {"X-API-Key": "test-admin-key"}

SOURCES = [
    {"id": "S1", "path": "superset/utils/cache.py", "language": "python", "title": "cache.py",
     "distance": 0.2, "score": None, "preview": "def generate_cache_key"},
]


def fake_answer(question, top_k=5, history=None, mode=None, language=None, path_prefix=None):
    fake_answer.calls.append({"question": question, "history": history, "language": language})
    return {
        "question": question,
        "standalone_question": question,
        "answer": "Cache keys are built in cache.py [S1].",
        "sources": SOURCES,
        "top_k": top_k,
        "model": "test-model",
        "retrieval_ms": 12,
        "generation_ms": 34,
    }


fake_answer.calls = []


def fake_stream(question, top_k=5, history=None, mode=None, language=None, path_prefix=None):
    yield "sources", {"sources": SOURCES, "standalone_question": question}
    yield "token", "Cache keys "
    yield "token", "live in cache.py [S1]."
    yield "done", {
        "answer": "Cache keys live in cache.py [S1].",
        "sources": SOURCES,
        "model": "test-model",
        "retrieval_ms": 5,
        "generation_ms": 6,
    }


@pytest.fixture()
def client(monkeypatch):
    fake_answer.calls.clear()
    monkeypatch.setattr(main, "ask_sentinel", fake_answer)
    monkeypatch.setattr(main, "stream_sentinel", fake_stream)
    with TestClient(main.app) as test_client:
        yield test_client


def new_session(client) -> str:
    response = client.post("/sessions", headers=ADMIN)
    assert response.status_code == 201
    return response.json()["session_id"]


def test_health_is_public(client):
    assert client.get("/health").json() == {"status": "ok", "service": "sentinel-api"}


@pytest.mark.parametrize(
    "method,path",
    [("get", "/"), ("post", "/query"), ("post", "/search"), ("post", "/sessions"), ("get", "/documents")],
)
def test_every_route_but_health_rejects_missing_key(client, method, path):
    assert getattr(client, method)(path).status_code == 401


def test_wrong_key_is_rejected(client):
    assert client.get("/documents", headers={"X-API-Key": "nope"}).status_code == 401


def test_query_returns_cited_answer_without_session(client):
    response = client.post("/query", json={"question": "where is the cache key built?"}, headers=ADMIN)

    body = response.json()
    assert response.status_code == 200
    assert body["answer"].endswith("[S1].")
    assert body["sources"][0]["path"] == "superset/utils/cache.py"
    assert body["session_id"] is None and body["message_id"] is None


def test_query_validates_input(client):
    assert client.post("/query", json={"question": "hi"}, headers=ADMIN).status_code == 422
    assert client.post("/query", json={"question": "valid question", "top_k": 16}, headers=ADMIN).status_code == 422
    bad_language = {"question": "valid question", "language": "cobol"}
    assert client.post("/query", json=bad_language, headers=ADMIN).status_code == 422


def test_session_keeps_history_and_sources(client):
    session_id = new_session(client)

    ask = lambda text: client.post("/query", json={"question": text, "session_id": session_id}, headers=ADMIN)  # noqa: E731
    first = ask("how are cache keys built?")
    second = ask("and where is it used?")

    assert first.json()["message_id"] and second.json()["message_id"]
    assert fake_answer.calls[0]["history"] == []
    assert [t["role"] for t in fake_answer.calls[1]["history"]] == ["user", "assistant"]

    detail = client.get(f"/sessions/{session_id}", headers=ADMIN).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant", "user", "assistant"]
    assert detail["messages"][1]["sources"][0]["id"] == "S1"
    assert detail["messages"][0]["sources"] is None


def test_unknown_session_returns_404(client):
    response = client.post("/query", json={"question": "valid question", "session_id": "missing"}, headers=ADMIN)

    assert response.status_code == 404
    assert client.get("/sessions/missing", headers=ADMIN).status_code == 404


def test_feedback_only_on_assistant_messages(client):
    session_id = new_session(client)
    answer_id = client.post(
        "/query", json={"question": "how are cache keys built?", "session_id": session_id}, headers=ADMIN
    ).json()["message_id"]
    user_message_id = answer_id - 1

    assert client.post(f"/messages/{answer_id}/feedback", json={"rating": 1}, headers=ADMIN).status_code == 200
    assert client.post(f"/messages/{user_message_id}/feedback", json={"rating": 1}, headers=ADMIN).status_code == 404
    assert client.post(f"/messages/{answer_id}/feedback", json={"rating": 0}, headers=ADMIN).status_code == 422


def test_stream_emits_sse_events_and_persists_the_turn(client):
    session_id = new_session(client)

    response = client.post(
        "/query/stream", json={"question": "how are cache keys built?", "session_id": session_id}, headers=ADMIN
    )

    assert response.headers["content-type"].startswith("text/event-stream")
    events = [block.split("\n") for block in response.text.strip().split("\n\n")]
    names = [lines[0].removeprefix("event: ") for lines in events]
    assert names == ["sources", "token", "token", "done"]

    done = json.loads(events[-1][1].removeprefix("data: "))
    assert done["message_id"] and done["session_id"] == session_id
    assert len(client.get(f"/sessions/{session_id}", headers=ADMIN).json()["messages"]) == 2


def test_api_keys_can_be_created_used_and_revoked(client):
    created = client.post("/admin/keys", json={"label": "ci"}, headers=ADMIN).json()
    user_headers = {"X-API-Key": created["key"]}

    assert client.post("/sessions", headers=user_headers).status_code == 201
    assert client.post("/admin/keys", json={}, headers=user_headers).status_code == 401

    assert client.delete(f"/admin/keys/{created['id']}", headers=ADMIN).status_code == 200
    assert client.post("/sessions", headers=user_headers).status_code == 401
    assert all("key" not in item for item in client.get("/admin/keys", headers=ADMIN).json())


def test_upload_rejects_unsupported_types_and_queues_supported_ones(client, monkeypatch):
    queued = []
    monkeypatch.setattr(main, "ingest_upload", lambda job_id, name, data: queued.append((job_id, name, len(data))))

    bad = client.post("/documents/upload", files={"file": ("virus.exe", b"MZ")}, headers=ADMIN)
    good = client.post("/documents/upload", files={"file": ("notes.md", b"# Notes\nhello")}, headers=ADMIN)

    assert bad.status_code == 415
    assert good.status_code == 202
    job_id = good.json()["job_id"]
    assert queued == [(job_id, "notes.md", 13)]

    job = client.get(f"/jobs/{job_id}", headers=ADMIN).json()
    assert job["status"] == "queued" and job["filename"] == "notes.md"
    assert client.get("/jobs/unknown", headers=ADMIN).status_code == 404


def test_upload_strips_directory_components_from_filename(client, monkeypatch):
    monkeypatch.setattr(main, "ingest_upload", lambda *args: None)

    response = client.post("/documents/upload", files={"file": ("..\\..\\etc\\guide.md", b"# hi")}, headers=ADMIN)

    assert response.json()["filename"] == "guide.md"


def test_documents_list_and_delete(client, monkeypatch):
    store.upsert_document("doc-1", "uploads/a.md", "upload", "markdown", "hash-a", 3)

    listing = client.get("/documents?limit=10", headers=ADMIN).json()
    assert any(item["id"] == "doc-1" and item["chunk_count"] == 3 for item in listing["items"])

    monkeypatch.setattr(main, "delete_indexed_document", lambda document_id: document_id == "doc-1")
    assert client.delete("/documents/doc-1", headers=ADMIN).json() == {"id": "doc-1", "deleted": True}
    assert client.delete("/documents/nope", headers=ADMIN).status_code == 404
