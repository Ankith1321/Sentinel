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


UPLOAD_SOURCE = "upload"


def list_documents(limit: int, offset: int, source: str | None = None) -> tuple[list[sqlite3.Row], int]:
    where, params = "", ()
    if source == UPLOAD_SOURCE:
        where, params = "WHERE source_type = ?", (UPLOAD_SOURCE,)
    elif source == "corpus":
        where, params = "WHERE source_type != ?", (UPLOAD_SOURCE,)
    with connect() as db:
        rows = db.execute(
            f"SELECT * FROM documents {where} ORDER BY path LIMIT ? OFFSET ?", (*params, limit, offset)
        ).fetchall()
        total = db.execute(f"SELECT COUNT(*) FROM documents {where}", params).fetchone()[0]
    return rows, total


def corpus_documents() -> dict[str, sqlite3.Row]:
    with connect() as db:
        rows = db.execute("SELECT * FROM documents WHERE source_type != ?", (UPLOAD_SOURCE,)).fetchall()
    return {row["path"]: row for row in rows}


def replace_corpus_manifest(rows: list[tuple[str, str, str, str | None, str, int]]) -> None:
    now = utc_now()
    with connect() as db:
        db.execute("DELETE FROM documents WHERE source_type != ?", (UPLOAD_SOURCE,))
        db.executemany(
            "INSERT INTO documents (id, path, source_type, language, content_hash, chunk_count, "
            "first_indexed_at, last_indexed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(*row, now, now) for row in rows],
        )


def document_counts() -> dict[str, int]:
    with connect() as db:
        rows = db.execute(
            "SELECT source_type, COUNT(*), COALESCE(SUM(chunk_count), 0) FROM documents GROUP BY source_type"
        ).fetchall()
    return {f"{r[0]}_files": r[1] for r in rows} | {f"{r[0]}_chunks": r[2] for r in rows}


def start_sync_run(pulled: bool) -> int:
    with connect() as db:
        cursor = db.execute(
            "INSERT INTO sync_runs (status, pulled, started_at) VALUES ('running', ?, ?)", (int(pulled), utc_now())
        )
        return cursor.lastrowid


def finish_sync_run(run_id: int, report: dict | None, error: str | None) -> None:
    report = report or {}
    with connect() as db:
        db.execute(
            """
            UPDATE sync_runs SET status = ?, commit_before = ?, commit_after = ?, scanned = ?, added = ?,
                changed = ?, removed = ?, unchanged = ?, chunks_written = ?, chunks_deleted = ?,
                verified_stale = ?, errors_json = ?, error = ?, finished_at = ?
            WHERE id = ?
            """,
            (
                "failed" if error else "done",
                report.get("commit_before"),
                report.get("commit_after"),
                report.get("scanned"),
                report.get("added"),
                report.get("changed"),
                report.get("removed"),
                report.get("unchanged"),
                report.get("chunks_written"),
                report.get("chunks_deleted"),
                report.get("verified_marked_stale"),
                json.dumps(report.get("errors", [])),
                error,
                utc_now(),
                run_id,
            ),
        )


def recent_sync_runs(limit: int) -> list[sqlite3.Row]:
    with connect() as db:
        return db.execute("SELECT * FROM sync_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


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
    needs_review: bool | None = None,
    message_id: int | None = None,
    verified_answer_id: int | None = None,
) -> None:
    with connect() as db:
        db.execute(
            """
            INSERT INTO query_log
                (session_id, question, standalone_question, retrieved_ids,
                 retrieval_ms, generation_ms, model, needs_review, message_id, verified_answer_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, question, standalone_question, json.dumps(retrieved_ids),
             retrieval_ms, generation_ms, model, None if needs_review is None else int(needs_review),
             message_id, verified_answer_id, utc_now()),
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


def create_verified_answer(question: str, answer: str, sources: list[dict], origin: str) -> int | None:
    with connect() as db:
        exists = db.execute(
            "SELECT 1 FROM verified_answers WHERE lower(question) = lower(?) AND status != 'rejected'", (question,)
        ).fetchone()
        if exists:
            return None
        cursor = db.execute(
            "INSERT INTO verified_answers (question, answer, sources_json, status, origin, created_at) "
            "VALUES (?, ?, ?, 'pending', ?, ?)",
            (question, answer, json.dumps(sources), origin, utc_now()),
        )
        return cursor.lastrowid


def list_verified_answers(status: str | None, limit: int, offset: int) -> tuple[list[sqlite3.Row], int]:
    where, params = ("WHERE status = ?", (status,)) if status else ("", ())
    with connect() as db:
        rows = db.execute(
            f"SELECT * FROM verified_answers {where} ORDER BY id DESC LIMIT ? OFFSET ?", (*params, limit, offset)
        ).fetchall()
        total = db.execute(f"SELECT COUNT(*) FROM verified_answers {where}", params).fetchone()[0]
    return rows, total


def verified_answer_counts() -> dict[str, int]:
    with connect() as db:
        rows = db.execute("SELECT status, COUNT(*) FROM verified_answers GROUP BY status").fetchall()
    counts = {"pending": 0, "approved": 0, "stale": 0, "rejected": 0}
    counts.update({r[0]: r[1] for r in rows})
    return counts


def get_verified_answer(answer_id: int) -> sqlite3.Row | None:
    with connect() as db:
        return db.execute("SELECT * FROM verified_answers WHERE id = ?", (answer_id,)).fetchone()


def approved_verified_answers() -> list[sqlite3.Row]:
    with connect() as db:
        return db.execute("SELECT * FROM verified_answers WHERE status = 'approved' ORDER BY id").fetchall()


def approve_verified_answer(answer_id: int, answer: str, source_hashes: dict[str, str]) -> None:
    with connect() as db:
        db.execute(
            "UPDATE verified_answers SET status = 'approved', answer = ?, source_hashes_json = ?, "
            "stale_reason = NULL, reviewed_at = ? WHERE id = ?",
            (answer, json.dumps(source_hashes), utc_now(), answer_id),
        )


def set_verified_status(answer_id: int, status: str, reason: str | None = None) -> None:
    with connect() as db:
        db.execute(
            "UPDATE verified_answers SET status = ?, stale_reason = ?, reviewed_at = ? WHERE id = ?",
            (status, reason, utc_now(), answer_id),
        )


def delete_verified_answer(answer_id: int) -> bool:
    with connect() as db:
        return db.execute("DELETE FROM verified_answers WHERE id = ?", (answer_id,)).rowcount > 0


def record_verified_served(answer_id: int) -> None:
    with connect() as db:
        db.execute(
            "UPDATE verified_answers SET times_served = times_served + 1, last_served_at = ? WHERE id = ?",
            (utc_now(), answer_id),
        )


def mark_verified_stale(changed_paths: set[str]) -> int:
    marked = 0
    for row in approved_verified_answers():
        touched = sorted(set(json.loads(row["source_hashes_json"])) & changed_paths)
        if touched:
            set_verified_status(row["id"], "stale", f"Source changed: {', '.join(touched)}")
            marked += 1
    return marked


def content_hashes(paths: list[str]) -> dict[str, str]:
    if not paths:
        return {}
    with connect() as db:
        rows = db.execute(
            f"SELECT path, content_hash FROM documents WHERE path IN ({','.join('?' * len(paths))})", paths
        ).fetchall()
    return {r["path"]: r["content_hash"] for r in rows}


def assistant_turn(message_id: int) -> tuple[str, sqlite3.Row] | None:
    with connect() as db:
        answer = db.execute(
            "SELECT * FROM messages WHERE id = ? AND role = 'assistant'", (message_id,)
        ).fetchone()
        if answer is None:
            return None
        question = db.execute(
            "SELECT content FROM messages WHERE session_id = ? AND role = 'user' AND id < ? "
            "ORDER BY id DESC LIMIT 1",
            (answer["session_id"], message_id),
        ).fetchone()
    return (question[0], answer) if question else None


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
