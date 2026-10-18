import hashlib
import json
import secrets
import sqlite3
from uuid import uuid4

from backend.app.db import connect, utc_now

HISTORY_TURNS = 10


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def get_document_by_path(path: str) -> sqlite3.Row | None:
    with connect() as db:
        return db.execute("SELECT * FROM documents WHERE path = ?", (path,)).fetchone()


def get_document(document_id: str) -> sqlite3.Row | None:
    with connect() as db:
        return db.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()


def list_documents(limit: int, offset: int) -> tuple[list[sqlite3.Row], int]:
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM documents ORDER BY path LIMIT ? OFFSET ?", (limit, offset)
        ).fetchall()
        total = db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    return rows, total


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


def create_job(filename: str) -> str:
    job_id = uuid4().hex
    with connect() as db:
        db.execute(
            "INSERT INTO jobs (id, filename, status, created_at) VALUES (?, ?, 'queued', ?)",
            (job_id, filename, utc_now()),
        )
    return job_id


def update_job(job_id: str, status: str, document_id: str | None = None, error: str | None = None) -> None:
    finished = utc_now() if status in {"done", "unchanged", "failed"} else None
    with connect() as db:
        db.execute(
            "UPDATE jobs SET status = ?, document_id = ?, error = ?, finished_at = ? WHERE id = ?",
            (status, document_id, error, finished, job_id),
        )


def get_job(job_id: str) -> sqlite3.Row | None:
    with connect() as db:
        return db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


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
) -> None:
    with connect() as db:
        db.execute(
            """
            INSERT INTO query_log
                (session_id, question, standalone_question, retrieved_ids,
                 retrieval_ms, generation_ms, model, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, question, standalone_question, json.dumps(retrieved_ids),
             retrieval_ms, generation_ms, model, utc_now()),
        )


def query_stats() -> dict:
    with connect() as db:
        totals = [
            row[0]
            for row in db.execute("SELECT retrieval_ms + generation_ms FROM query_log ORDER BY 1").fetchall()
        ]
        averages = db.execute("SELECT AVG(retrieval_ms), AVG(generation_ms) FROM query_log").fetchone()
        ratings = db.execute(
            "SELECT COALESCE(SUM(rating = 1), 0), COALESCE(SUM(rating = -1), 0) FROM feedback"
        ).fetchone()
        per_day = db.execute(
            "SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS queries FROM query_log "
            "GROUP BY day ORDER BY day DESC LIMIT 14"
        ).fetchall()

    rated = ratings[0] + ratings[1]
    return {
        "queries": len(totals),
        "avg_retrieval_ms": round(averages[0] or 0),
        "avg_generation_ms": round(averages[1] or 0),
        "p95_total_ms": totals[min(len(totals) - 1, int(len(totals) * 0.95))] if totals else 0,
        "feedback_up": ratings[0],
        "feedback_down": ratings[1],
        "feedback_positive_ratio": round(ratings[0] / rated, 3) if rated else None,
        "queries_per_day": [{"day": r["day"], "queries": r["queries"]} for r in per_day],
    }


def create_api_key(label: str | None) -> tuple[str, str]:
    key_id = uuid4().hex
    raw_key = f"snt_{secrets.token_urlsafe(32)}"
    with connect() as db:
        db.execute(
            "INSERT INTO api_keys (id, key_hash, label, created_at) VALUES (?, ?, ?, ?)",
            (key_id, hash_secret(raw_key), label, utc_now()),
        )
    return key_id, raw_key


def api_key_is_active(raw_key: str) -> bool:
    with connect() as db:
        row = db.execute(
            "SELECT 1 FROM api_keys WHERE key_hash = ? AND revoked_at IS NULL", (hash_secret(raw_key),)
        ).fetchone()
    return row is not None


def list_api_keys() -> list[sqlite3.Row]:
    with connect() as db:
        return db.execute("SELECT id, label, created_at, revoked_at FROM api_keys ORDER BY created_at").fetchall()


def revoke_api_key(key_id: str) -> bool:
    with connect() as db:
        cursor = db.execute(
            "UPDATE api_keys SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL", (utc_now(), key_id)
        )
        return cursor.rowcount > 0
