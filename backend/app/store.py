import json
import sqlite3
from uuid import uuid4

from backend.app.db import connect, utc_now

HISTORY_TURNS = 10


def corpus_documents() -> dict[str, sqlite3.Row]:
    with connect() as db:
        rows = db.execute("SELECT * FROM documents").fetchall()
    return {row["path"]: row for row in rows}


def replace_corpus_manifest(rows: list[tuple[str, str, str, str | None, str, int]]) -> None:
    now = utc_now()
    with connect() as db:
        db.execute("DELETE FROM documents")
        db.executemany(
            "INSERT INTO documents (id, path, source_type, language, content_hash, chunk_count, "
            "first_indexed_at, last_indexed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(*row, now, now) for row in rows],
        )


def upsert_document(
    document_id: str,
    path: str,
    source_type: str,
    language: str | None,
    content_hash: str,
    chunk_count: int,
) -> None:
    now = utc_now()
    with connect() as db:
        db.execute(
            """
            INSERT INTO documents
                (id, path, source_type, language, content_hash, chunk_count, first_indexed_at, last_indexed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                source_type = excluded.source_type,
                language = excluded.language,
                content_hash = excluded.content_hash,
                chunk_count = excluded.chunk_count,
                last_indexed_at = excluded.last_indexed_at
            """,
            (document_id, path, source_type, language, content_hash, chunk_count, now, now),
        )


def delete_document(document_id: str) -> bool:
    with connect() as db:
        cursor = db.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        return cursor.rowcount > 0


def create_session() -> str:
    session_id = uuid4().hex
    now = utc_now()
    with connect() as db:
        db.execute("INSERT INTO sessions (id, created_at, last_active_at) VALUES (?, ?, ?)", (session_id, now, now))
    return session_id


def get_session(session_id: str) -> sqlite3.Row | None:
    with connect() as db:
        return db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()


def list_sessions(limit: int) -> list[sqlite3.Row]:
    with connect() as db:
        return db.execute(
            """
            SELECT s.id, s.created_at, s.last_active_at,
                   (SELECT content FROM messages m WHERE m.session_id = s.id AND m.role = 'user'
                    ORDER BY m.id LIMIT 1) AS first_question
            FROM sessions s ORDER BY s.last_active_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()


def add_message(session_id: str, role: str, content: str, sources: list[dict] | None = None) -> int:
    now = utc_now()
    with connect() as db:
        cursor = db.execute(
            "INSERT INTO messages (session_id, role, content, sources_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, role, content, json.dumps(sources) if sources is not None else None, now),
        )
        db.execute("UPDATE sessions SET last_active_at = ? WHERE id = ?", (now, session_id))
        return cursor.lastrowid


def list_messages(session_id: str) -> list[sqlite3.Row]:
    with connect() as db:
        return db.execute("SELECT * FROM messages WHERE session_id = ? ORDER BY id", (session_id,)).fetchall()


def recent_turns(session_id: str, turns: int = HISTORY_TURNS) -> list[dict]:
    with connect() as db:
        rows = db.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, turns * 2),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def get_message(message_id: int) -> sqlite3.Row | None:
    with connect() as db:
        return db.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()


def add_feedback(message_id: int, rating: int) -> None:
    with connect() as db:
        db.execute(
            "INSERT INTO feedback (message_id, rating, created_at) VALUES (?, ?, ?)",
            (message_id, rating, utc_now()),
        )


def add_query_log(
    session_id: str | None,
    question: str,
    standalone_question: str,
    retrieved_ids: list[str],
    retrieval_ms: int,
    generation_ms: int,
    model: str,
    needs_review: bool | None = None,
    message_id: int | None = None,
) -> None:
    with connect() as db:
        db.execute(
            """
            INSERT INTO query_log
                (session_id, question, standalone_question, retrieved_ids,
                 retrieval_ms, generation_ms, model, needs_review, message_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, question, standalone_question, json.dumps(retrieved_ids),
             retrieval_ms, generation_ms, model, None if needs_review is None else int(needs_review),
             message_id, utc_now()),
        )
