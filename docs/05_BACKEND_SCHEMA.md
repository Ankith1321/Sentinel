# Backend Schema

**Project:** Sentinel
**Status:** Implemented in `backend/app/db.py` (SQLite, `data/sentinel.db`) and used through `backend/app/store.py`. The `documents` table is populated by uploads; the bulk Superset index is tracked in ChromaDB only, so `GET /documents` lists uploaded files.
**Related:** [`02_TRD.md`](02_TRD.md) · [`06_IMPLEMENTATION_PLAN.md`](06_IMPLEMENTATION_PLAN.md)

## 1. Current state

Storage is split across three places:

- `data/processed/chunks.jsonl` — flat file, one JSON object per chunk (rebuildable).
- ChromaDB (`data/indexes/chroma/`) — vector store, which also holds each chunk's `content` and `metadata` (`source_id`, `path`, `language`, `title`, `chunk_index`).
- SQLite (`data/sentinel.db`) — everything relational, described below.

The split exists because upload tracking needs content hashes, and sessions and message history are relational data, not vector data.

## 2. Decision

Add SQLite for everything structural. This is a file-based, zero-extra-infrastructure choice, consistent with the pattern ChromaDB already set — don't reach for external infra until there's an actual reason to. ChromaDB is not being replaced; it keeps doing exactly what it does now (vector search). Migrate to Postgres only if and when this needs to run as more than one instance — that's a future decision, deliberately not built prematurely.

## 3. Schema

### `documents`

Tracks every source file that has been ingested. This table is what makes hash-based incremental ingestion possible, and it directly fixes the current bug where `loader.py` mints a fresh UUID per run instead of a stable, path-derived identity. Identity comes from the path; change detection comes from `content_hash`.

```sql
CREATE TABLE documents (
    id               TEXT PRIMARY KEY,      -- stable id derived from path, not a fresh UUID per run
    path             TEXT NOT NULL UNIQUE,
    source_type      TEXT NOT NULL,         -- 'code' | 'markdown' | future: 'pdf', 'docx'
    language         TEXT,
    content_hash     TEXT NOT NULL,         -- SHA-256 of file content, per CONTEXT.md rule 8.1
    chunk_count      INTEGER NOT NULL DEFAULT 0,
    first_indexed_at TEXT NOT NULL,         -- ISO 8601
    last_indexed_at  TEXT NOT NULL
);

CREATE INDEX idx_documents_content_hash ON documents(content_hash);
```

Ingestion flow against this table: hash the file, look up by `path`, compare `content_hash` — unchanged means skip, changed means delete every existing chunk for that `source_id` from Chroma first, then re-chunk/re-embed and upsert using the same `document.id` prefix so `chunk_id` stays stable, then update `last_indexed_at`. The delete-first step is required: upsert only overwrites chunk ids that still exist, so a file that shrinks from 10 chunks to 6 would otherwise leave chunks 7-10 behind and keep serving stale content. The same delete applies when a file is removed or renamed.

### `sessions`

Phase 6 — one row per conversation.

```sql
CREATE TABLE sessions (
    id             TEXT PRIMARY KEY,
    created_at     TEXT NOT NULL,
    last_active_at TEXT NOT NULL
);
```

### `messages`

```sql
CREATE TABLE messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role       TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content    TEXT NOT NULL,
    sources_json TEXT,                 -- assistant turns only: the source cards shown with that answer
    created_at TEXT NOT NULL
);

CREATE INDEX idx_messages_session_id ON messages(session_id);
```

### `feedback`

Phase 9 — thumbs up/down per assistant message.

```sql
CREATE TABLE feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    rating     INTEGER NOT NULL CHECK (rating IN (-1, 1)),
    created_at TEXT NOT NULL
);
```

### `jobs`

Phase 4 — one row per background upload, so `POST /documents/upload` can return a job id immediately and the UI can poll `GET /jobs/{id}`.

```sql
CREATE TABLE jobs (
    id          TEXT PRIMARY KEY,
    document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
    filename    TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('queued', 'processing', 'done', 'unchanged', 'failed')),
    error       TEXT,
    created_at  TEXT NOT NULL,
    finished_at TEXT
);
```

### `api_keys`

Phase 7.

```sql
CREATE TABLE api_keys (
    id         TEXT PRIMARY KEY,
    key_hash   TEXT NOT NULL UNIQUE,   -- hashed, the raw key is never stored
    label      TEXT,
    created_at TEXT NOT NULL,
    revoked_at TEXT
);
```

## 4. Division of responsibility

- **ChromaDB:** vector embeddings, chunk content, chunk-level metadata used for retrieval (path, language, title, chunk_index) — anything that needs similarity search.
- **SQLite:** anything relational — document-level tracking for incremental ingestion, sessions, messages, feedback, auth. Nothing here needs vector search.
- `chunk_id` (already `{source_id}::chunk_{idx}` in `ChunkRecord`) is the join key back to `documents.id` if a chunk-level table is ever needed. Not creating one now — `DELETE /documents/{id}` can delete by a `source_id` metadata filter directly in Chroma, which it already supports, so a dedicated chunks table would be speculative until something actually needs it.

## 5. Explicitly not doing (and why)

- **No `users` table.** Phase 7 auth is API-key based, not account based. A `users` table gets built when there's an actual multi-user requirement, not ahead of one.
- **No full-text search table.** BM25 (Phase 3) can run in-process over existing JSONL/Chroma content at query time. Only worth a dedicated FTS table if that becomes a measured bottleneck — not assumed upfront.
