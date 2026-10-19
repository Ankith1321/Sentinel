# Backend Schema

**Project:** Sentinel
**Status:** Implemented in `backend/app/db.py` (SQLite, `data/sentinel.db`) and used through `backend/app/store.py`. `init_db()` creates missing tables and adds columns introduced later, so an existing database upgrades in place. Last updated 2026-10-19.
**Related:** [`02_TRD.md`](02_TRD.md) · [`06_IMPLEMENTATION_PLAN.md`](06_IMPLEMENTATION_PLAN.md)

## 1. Where data lives

- `data/processed/chunks.jsonl`: the chunk file from the last full build (rebuildable, gitignored).
- ChromaDB (`data/indexes/chroma/`, collection `superset_codebase`): one entry per chunk with its embedding, text and metadata (`source_id`, `source_type`, `path`, `language`, `title`, `chunk_index`). Anything that needs similarity search.
- In memory, inside the API process: the BM25 keyword index and the symbol-definition map, both built from ChromaDB at start-up and rebuilt after uploads and syncs that change files.
- SQLite (`data/sentinel.db`, gitignored): everything relational, below.

## 2. Tables

### `documents`: the file manifest

One row per indexed file: every corpus file (written by a full build and kept current by the sync) and every upload (`source_type = 'upload'`). Identity comes from the path (`id` is the first 32 hex characters of SHA-256 of the relative path); change detection comes from `content_hash`.

```sql
CREATE TABLE documents (
    id               TEXT PRIMARY KEY,
    path             TEXT NOT NULL UNIQUE,
    source_type      TEXT NOT NULL,          -- 'code' for corpus files, 'upload' for uploads
    language         TEXT,
    content_hash     TEXT NOT NULL,          -- SHA-256 of the file text (rule 8.1)
    chunk_count      INTEGER NOT NULL DEFAULT 0,
    first_indexed_at TEXT NOT NULL,
    last_indexed_at  TEXT NOT NULL
);
CREATE INDEX idx_documents_content_hash ON documents(content_hash);
```

**Re-indexing a file (sync and upload):** compare `content_hash`. If unchanged, skip. If changed, chunk and embed, **upsert the new chunks first, then delete that source's chunk ids the new version no longer produces**. A search therefore never sees the file missing, and a file that shrinks leaves nothing stale behind. A file that disappears loses all its chunks and its row. A full build replaces every non-upload row and never deletes upload chunks.

### `jobs`: background uploads

```sql
CREATE TABLE jobs (
    id          TEXT PRIMARY KEY,            -- returned by POST /documents/upload
    document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
    filename    TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('queued', 'processing', 'done', 'unchanged', 'failed')),
    error       TEXT,
    created_at  TEXT NOT NULL,
    finished_at TEXT
);
```

### `sessions` and `messages`: conversations

```sql
CREATE TABLE sessions (
    id             TEXT PRIMARY KEY,
    created_at     TEXT NOT NULL,
    last_active_at TEXT NOT NULL
);

CREATE TABLE messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role         TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content      TEXT NOT NULL,
    sources_json TEXT,                       -- assistant turns: the source cards shown with that answer
    created_at   TEXT NOT NULL
);
CREATE INDEX idx_messages_session_id ON messages(session_id);
```

### `feedback`

```sql
CREATE TABLE feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    rating     INTEGER NOT NULL CHECK (rating IN (-1, 1)),
    created_at TEXT NOT NULL
);
```

### `query_log`: one row per answered question

```sql
CREATE TABLE query_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT,
    question            TEXT NOT NULL,
    standalone_question TEXT NOT NULL,       -- after follow-up rewriting
    retrieved_ids       TEXT NOT NULL,       -- JSON array of chunk ids ([] for a verified answer)
    retrieval_ms        INTEGER NOT NULL,
    generation_ms       INTEGER NOT NULL,    -- 0 for a verified answer
    model               TEXT NOT NULL,       -- model id, or 'verified-answer'
    needs_review        INTEGER,             -- answer checker result; NULL when not checked
    message_id          INTEGER,             -- the assistant message, when asked inside a session
    verified_answer_id  INTEGER,             -- set when served from verified_answers
    created_at          TEXT NOT NULL
);
```

### `sync_runs`: incremental index syncs

```sql
CREATE TABLE sync_runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    status         TEXT NOT NULL CHECK (status IN ('running', 'done', 'failed')),
    pulled         INTEGER NOT NULL DEFAULT 0,  -- 1 if `git pull --ff-only` ran first
    commit_before  TEXT,
    commit_after   TEXT,
    scanned        INTEGER,
    added          INTEGER,
    changed        INTEGER,
    removed        INTEGER,
    unchanged      INTEGER,
    chunks_written INTEGER,
    chunks_deleted INTEGER,
    verified_stale INTEGER,                  -- approved answers marked stale by this run
    errors_json    TEXT,                     -- per-file errors; one bad file never stops a run
    error          TEXT,
    started_at     TEXT NOT NULL,
    finished_at    TEXT
);
```

### `verified_answers`: admin-approved answers served without search

```sql
CREATE TABLE verified_answers (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    question           TEXT NOT NULL,
    answer             TEXT NOT NULL,
    sources_json       TEXT NOT NULL,              -- the source cards cited by the answer
    source_hashes_json TEXT NOT NULL DEFAULT '{}', -- {path: content_hash} captured at approval
    status             TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'stale', 'rejected')),
    origin             TEXT NOT NULL CHECK (origin IN ('generated', 'chat')),
    stale_reason       TEXT,
    times_served       INTEGER NOT NULL DEFAULT 0,
    created_at         TEXT NOT NULL,
    reviewed_at        TEXT,
    last_served_at     TEXT
);
CREATE INDEX idx_verified_answers_status ON verified_answers(status);
```

Lifecycle:
- **Created as `pending`,** either drafted by the model for a question (`generated`) or promoted from a chat answer (`chat`). The same question cannot be queued twice unless the earlier one was rejected.
- **Becomes `approved`** only through an admin. Approval requires at least one valid `[S#]` citation and records the current `content_hash` of every cited file.
- **Becomes `stale`** when a sync changes or removes a cited file, or when the matcher sees a cited file's hash differ from the one recorded at approval. Stale answers are never served.
- **`rejected`** answers are kept and never served.
- **Only `approved` rows are ever served.** A question gets one when it is within 0.91 cosine similarity of the approved question, and every code name it mentions also appears in the approved question.

### `api_keys`

```sql
CREATE TABLE api_keys (
    id         TEXT PRIMARY KEY,
    key_hash   TEXT NOT NULL UNIQUE,   -- SHA-256; the raw key is shown once and never stored
    label      TEXT,
    created_at TEXT NOT NULL,
    revoked_at TEXT
);
```

The bootstrap admin key (`SENTINEL_API_KEY` in `.env`) is not stored here. Keys in this table are regular keys (for example the frontend proxy's) and are refused on `/admin/*`.

## 3. Division of responsibility

- **ChromaDB:** embeddings, chunk text and chunk metadata used for retrieval.
- **SQLite:** everything relational: the file manifest, jobs, conversations, feedback, the query log, sync runs, verified answers and API keys.
- **Join key:** `chunk_id` (`{source_id}::chunk_{n}`) links chunks back to `documents.id`. There is no chunk table: deleting by `source_id` metadata in Chroma covers every current need.

## 4. Explicitly not doing

- **No `users` table.** There are no user accounts; the only sign-in is the admin's, with the bootstrap key.
- **No full-text search table.** BM25 runs in memory; revisit only if that becomes a measured bottleneck.
- **No embeddings in SQLite.** The verified-answer matcher embeds approved questions in memory when it loads them; there are tens to hundreds of them, so that takes well under a second.
