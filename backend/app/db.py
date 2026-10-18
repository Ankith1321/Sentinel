import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

from ingestion.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id               TEXT PRIMARY KEY,
    path             TEXT NOT NULL UNIQUE,
    source_type      TEXT NOT NULL,
    language         TEXT,
    content_hash     TEXT NOT NULL,
    chunk_count      INTEGER NOT NULL DEFAULT 0,
    first_indexed_at TEXT NOT NULL,
    last_indexed_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash);

CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
    filename    TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('queued', 'processing', 'done', 'unchanged', 'failed')),
    error       TEXT,
    created_at  TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id             TEXT PRIMARY KEY,
    created_at     TEXT NOT NULL,
    last_active_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role         TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content      TEXT NOT NULL,
    sources_json TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);

CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    rating     INTEGER NOT NULL CHECK (rating IN (-1, 1)),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS query_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT,
    question            TEXT NOT NULL,
    standalone_question TEXT NOT NULL,
    retrieved_ids       TEXT NOT NULL,
    retrieval_ms        INTEGER NOT NULL,
    generation_ms       INTEGER NOT NULL,
    model               TEXT NOT NULL,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_keys (
    id         TEXT PRIMARY KEY,
    key_hash   TEXT NOT NULL UNIQUE,
    label      TEXT,
    created_at TEXT NOT NULL,
    revoked_at TEXT
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    with connect() as connection:
        connection.executescript(SCHEMA)
