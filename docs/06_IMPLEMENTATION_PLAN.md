# Implementation Plan

**Project:** Sentinel
**Status:** The source of truth for what "done" means and where each phase stands. `CONTEXT.md` section 9 is history. The admin dashboard reads the phase list below (`## Phase … — …` headings and `**Status: …**` lines), so keep that format. Last updated 2026-10-19.
**Related:** [`01_PRD.md`](01_PRD.md) · [`02_TRD.md`](02_TRD.md) · [`03_APP_FLOW.md`](03_APP_FLOW.md) · [`05_BACKEND_SCHEMA.md`](05_BACKEND_SCHEMA.md)

## Phase 1 — Fix what's broken

**Status: done.** Fixed and verified live (commits `74b61af` to `7fd53a3`).

**Definition of done:** `/query` returns a cited answer over real HTTP; the embedding model is a singleton; no dead files or unreachable code; the frontend renders success and error states.

## Phase 1.5 — Minimal eval set

**Status: done.** Baseline on the original line-window index: hit@5 40%, hit@1 17.5%, MRR 0.267. Every later run is in `eval/results/` and on the dashboard.

**Definition of done:** `eval/qa_set.json` holds 30-40 questions with expected source paths chosen by reading the Superset repo; `eval/run_eval.py` reports hit@1/5/10 and MRR, lists misses, and writes a timestamped result.

## Phase 2 — Chunking upgrade

**Status: done.** Python is cut at def/class boundaries with `ast`, TS/JS at top-level declarations, Markdown at headings. Every chunk starts with its file path; the Apache licence header is stripped; chunks under 20 tokens are dropped. Sizes are 200 target / 240 max tokens of the embedding model (rule 8.4 amended in `CONTEXT.md`: the measured best, and inside MiniLM's 256-token window).

**Definition of done:** semantic boundaries, token-measured sizes, noise filter, and no retrieval regression on the eval. Result: vector hit@5 40% → 50% on the same embedder.

## Phase 3 — Retrieval upgrade

**Status: done.** Vector + BM25 + a symbol-definition index, fused with weighted Reciprocal Rank Fusion; test files demoted; language and path-prefix filters on `/search` and `/query`; per-query retrieval logging; bge-small embeddings. The cross-encoder is built but off, because it never improved the eval. Archived per-release doc copies are not indexed. Current: hit@1 47.5%, hit@5 67.5%, MRR 0.559 on 146,435 chunks.

**Definition of done:** hybrid retrieval, fusion, filters, and a measured hit-rate gain on the fixed eval set.

## Phase 4 — Ingestion API and incremental sync

**Status: done.** Uploads return 202 with a job id and index in the background; unchanged re-uploads are a no-op; delete removes chunks. The corpus sync (`POST /admin/sync`, `python -m backend.app.sync`) hashes every file against the manifest and re-indexes only changes: verified on the real corpus with a no-change run (about 5 s), a real edit, and its revert. PDF and DOCX extraction are implemented but untested with real files.

**Definition of done:** upload, hash check, background processing, list and delete against real data, and an index that follows corpus changes without a full rebuild.

## Phase 5 — LLM upgrade

**Status: done, with one gap.** Local `Qwen2.5-3B-Instruct` (fp16, strict citation prompt) is the project model by owner decision (licence: non-commercial only). The Claude path is used whenever `ANTHROPIC_API_KEY` is set but has not run against the real API. Streaming over SSE, a whole-chunk context budget, at most 500 new tokens, and one generation at a time on the GPU.

**Definition of done:** an API model path behind a key, a documented local fallback, `POST /query/stream`, and a context budget that never cuts a chunk.

## Phase 6 — Conversation memory

**Status: done.** Verified live: "Which methods does it provide for querying?" was rewritten to "What methods does the BaseDAO class provide for querying?" before retrieval; turns are stored with their sources; the last 10 turns go to the model.

**Definition of done:** sessions and messages live, `POST /sessions` and `GET /sessions/{id}` working, follow-up rewriting verified by a real multi-turn test.

## Phase 7 — Authentication

**Status: done.** Every route except `/health` needs `X-API-Key`; keys are hashed; `/admin/*` needs the bootstrap admin key; the frontend proxy uses a regular key; admin access in the browser goes through an HttpOnly session cookie. Verified with nine live access checks (visitor, wrong key, admin, sign-out).

**Definition of done:** missing or invalid keys rejected everywhere but `/health`, hashed key storage, and admin generate/revoke.

## Phase 8 — Frontend upgrade

**Status: done.** Chat with streaming, citation chips, source cards, review notes and verified badges; sessions sidebar; sources slider; feedback; Documents page with uploads and a codebase view; admin dashboard. Checked in a real browser (Edge via Playwright) at desktop width and at 390 px; a phone-width overflow was found and fixed.

**Definition of done:** matches `03_APP_FLOW.md`, every screen wired to a tested endpoint.

## Phase 9 — Observability

**Status: done.** Every answered question is stored in `query_log` (retrieved ids, timings, model, checker result, message and verified-answer ids) and logged; feedback persists; the admin dashboard shows usage, latency, flagged answers, feedback, eval history, sync runs and the plan.

**Definition of done:** structured query logs, persisted feedback, the eval suite, and a dashboard.

## Phase 10 — Deploy and CI/CD

**Status: partly done.** The GitHub Actions workflow, both Dockerfiles and the compose file are written but have not been run: Docker Desktop was not running and the branch has not been pushed. Nothing is deployed to Azure yet; that needs a subscription, a registry and secrets from the owner. In a CPU-only container the answer path should be Claude.

**Definition of done:** both containers on Azure Container Apps behind the API key, CI building and pushing images, and the README linking the live demo.

## Phase 11 — Verified answers

**Status: done.** Owner request (2026-10-19): known questions are answered from a database, not by searching again. Admin-approved answers live in `verified_answers`. A new question is served one when it is within 0.91 cosine of an approved question, names no code symbol the approved question lacks, and none of the cited files changed since approval. Approval requires a valid citation; syncs mark affected answers stale. The admin reviews drafts on the dashboard (60 starter questions drafted by the 3B, plus chat answers promoted with "Make verified"). Matching on 40 paraphrase/near-miss pairs: precision 100%, recall 45%.

**Definition of done:** answers served only after human approval, citations kept, automatic staleness on source changes, a measured zero-false-match threshold, and an admin review UI.

## Sequencing note

The eval suite was pulled forward to Phase 1.5 because Phases 2 and 3 could not be judged without a baseline. The same rule holds for any future change: measure on the fixed eval sets before and after, and keep only what the numbers support.
