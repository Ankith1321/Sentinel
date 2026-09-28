# Implementation Plan

**Project:** Sentinel
**Status:** Supersedes the phase list in `docs/CONTEXT.md` section 9 — same phases, but each now has an explicit definition of done tied back to the PRD's success metrics and the App Flow/Schema decisions above. Treat this file as the current source of truth for "what does done mean"; `CONTEXT.md` section 9 should be read as historical context from here forward, not the active plan.
**Related:** [`01_PRD.md`](01_PRD.md) · [`02_TRD.md`](02_TRD.md) · [`03_APP_FLOW.md`](03_APP_FLOW.md) · [`05_BACKEND_SCHEMA.md`](05_BACKEND_SCHEMA.md)

## Phase 1 — Fix what's broken

**Status: done.** Fixed and verified live in a working session, not just read for correctness — see `ankith` branch commits `74b61af` through `7fd53a3`.

**Definition of done:** `/query` returns a cited answer over real HTTP (verified with curl and in an actual browser session against a real local model run); the embedding model is a singleton, not reloaded per call (verified — two calls reuse the same instance, ~35-40ms each); no dead files or unreachable code remain; the frontend renders both success and error states (verified in-browser).

## Phase 2 — Chunking upgrade

**Definition of done:** Python files chunk at function/class boundaries using the `ast` module instead of raw line windows. Chunk size is measured and capped in tokens (512 target, 1024 max), not lines. Chunks under 20 tokens are rejected as noise. Verified by re-running the eval set from Phase 9 and confirming retrieval hit-rate does not regress — "better chunking" is not a claim this project gets to make without a before/after number.

## Phase 3 — Retrieval upgrade

**Definition of done:** A BM25 index runs alongside Chroma; Reciprocal Rank Fusion merges the two result sets; a cross-encoder re-ranks the top-20 candidates down to the top-5 returned; metadata pre-filtering (language, path prefix) works on both `/search` and `/query`. Verified against the same fixed eval set as Phase 2 — this phase's entire justification is a hit-rate number going up, so it does not ship without one.

## Phase 4 — Ingestion API

**Definition of done:** `POST /documents/upload` accepts a file, computes its SHA-256, checks it against the `documents` table (see `05_BACKEND_SCHEMA.md`), responds immediately with a job id, and processes in a `BackgroundTasks` job — never blocking the request thread. Re-uploading an unchanged file is a verified no-op. `GET /documents` and `DELETE /documents/{id}` both work against real ingested data, not just the happy path with one test file.

## Phase 5 — LLM upgrade

**Definition of done:** An API-based model (Claude Haiku or GPT-4o-mini) is the default generation path, gated behind `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`. Local Qwen remains in the codebase as an explicit, documented fallback — not deleted, since "runs fully on-prem" is a legitimate story for data-sensitive deployments, just not the default. `GET /query/stream` exists and streams tokens over SSE. Context is trimmed to a token budget when it would exceed the model's window, never silently truncated mid-chunk.

## Phase 6 — Conversation memory

**Definition of done:** The `sessions` and `messages` tables from `05_BACKEND_SCHEMA.md` are live. `POST /sessions` and `GET /sessions/{id}` work end to end. The last 10 turns of a session are passed into the prompt. A follow-up question ("what about the other one?") gets reformulated into a self-contained query before it's embedded — verified with a real manual multi-turn test, not a single-turn eval run twice.

## Phase 7 — Authentication

**Definition of done:** Every route except `/health` rejects a request with a missing or invalid `X-API-Key` header. Keys are stored hashed in the `api_keys` table — the raw key is never persisted, only shown once at generation time. A minimal admin path exists to generate and revoke a key.

## Phase 8 — Frontend upgrade

**Definition of done:** Matches `03_APP_FLOW.md` exactly — chat thread view, streaming render, upload screen, top-k slider, feedback buttons. Every one of these is wired to a real, already-tested backend endpoint; no UI ships ahead of the endpoint it depends on.

## Phase 9 — Observability

**Definition of done:** Every query is logged with its text, retrieved chunk ids, and latency in milliseconds. Feedback persists to the `feedback` table. The eval suite (the same fixed 30-40 Q&A pairs referenced throughout the PRD and this plan) exists and produces one trackable retrieval-hit-rate number.

## Sequencing note — read before starting Phase 2

The eval suite is filed under Phase 9, but Phase 2 and Phase 3's own definitions of done both require it to already exist — you cannot verify "chunking got better" or "hybrid search improved hit-rate" without a baseline number to compare against. Building the full observability stack (structured logging, feedback persistence, a dashboard) can genuinely wait until Phase 9. A minimal version of just the eval set — 30-40 questions, expected source files, a script that reports a hit-rate percentage — cannot wait, and should be pulled forward and built before Phase 2 starts. This is the one real deviation from the original phase order, and it's a correction worth making now rather than discovering after Phase 2 and 3 ship with no way to know if they actually helped.
