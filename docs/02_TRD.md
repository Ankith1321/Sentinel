# Technical Requirements Document (TRD)

**Project:** Sentinel
**Status:** Living document. Update it when a stack or infrastructure decision changes. Last updated 2026-10-19.
**Related:** [`01_PRD.md`](01_PRD.md) · [`CONTEXT.md`](CONTEXT.md) · [`05_BACKEND_SCHEMA.md`](05_BACKEND_SCHEMA.md)

## 1. Overview

Sentinel is a retrieval-augmented generation service: a FastAPI backend that chunks and embeds a source codebase into ChromaDB, retrieves the most relevant chunks for a natural-language question, and generates a cited answer from an LLM, unless an administrator-approved answer already covers the question. A Next.js frontend is the reference client. This document records *why* each technical choice was made, not just what it is. The decision table below is what future changes should be checked against before being reverted or second-guessed.

## 2. Architecture

Two lifecycles share one vector store and one SQLite database:

- **Index time.** A full build (`ingestion.chunker` then `ingestion.build_vectorstore`) scans, loads, chunks, embeds and upserts the whole corpus and records a per-file manifest. After that, the incremental sync (`POST /admin/sync` or `python -m backend.app.sync`) hashes every file against the manifest and re-indexes only what changed, removed or appeared. Uploads go through the same chunk-embed-upsert path in a background task.
- **Query time.** Rewrite a follow-up into a standalone question, then check the verified-answers database. On a match, return the approved answer. Otherwise run vector search, BM25 and the symbol-definition index, fuse them, trim to a token budget, generate with the LLM, check the answer's citations, then stream it and log it.

Each half is a single Python process (a CLI or the FastAPI app). There is no message queue and no load balancer: this is a single-instance service by design. Only one process may write to the index at a time, which is why the sync normally runs inside the API process.

## 3. Stack decisions

| Layer | Choice | Why | Rejected |
|---|---|---|---|
| API framework | FastAPI | Native async, Pydantic validation at the boundary, free OpenAPI docs | Flask (no native async without extra tooling), Django (too heavy for a single API with no admin/ORM need) |
| Vector store | ChromaDB, persistent local client | Zero external infrastructure; holds 146,435 chunks on one machine | Pinecone/Qdrant: real options once this must scale past one machine or run several instances |
| Relational store | SQLite (`data/sentinel.db`) | One file, no server; holds the manifest, sessions, messages, feedback, jobs, sync runs, verified answers, query log and API keys | PostgreSQL: only once there is more than one API instance |
| Embedding model | `BAAI/bge-small-en-v1.5`, 384-dim | Won the eval: vector hit@5 70% against 50% for `all-MiniLM-L6-v2` on the same chunks. Small enough for CPU containers. Chunks are 200 target / 240 max tokens: 400-token chunks scored worse (MRR 0.453 against 0.506), and MiniLM's 256-token window would truncate the rule-8.4 sizes silently | MiniLM (lower recall), bge-large (3x storage, slower; no eval number to justify it), a BGE query prefix (vector hit@5 dropped to 60%) |
| Keyword search | `rank_bm25` in memory, plus a symbol-definition map | BM25 catches exact identifiers that vectors miss; the definition map sends "where is X defined" to the defining chunk (identifier questions 100% at rank 1) | OpenSearch/Elasticsearch: only when the in-memory index outgrows RAM |
| Fusion and re-ranking | Weighted Reciprocal Rank Fusion (vector 1, BM25 1, definitions 3), test files demoted x0.6 | No score calibration needed across very different scorers; each weight was set by the eval | MS MARCO cross-encoder: built and kept opt-in (`hybrid_rerank`) because it lowered or did not change hit@5 in every comparison |
| LLM (generation) | Local `Qwen/Qwen2.5-3B-Instruct`, fp16, with the strict citation prompt (owner decision 2026-10-19). Claude (`claude-haiku-5-5`) is used instead when `ANTHROPIC_API_KEY` is set | The 3B with the strict prompt matched the 7B on the answer eval (100% cited, 85% right file, 7/8 refusals) at half the latency, and fits in fp16 next to the embedder on an 8 GB GPU. **Licence: Qwen Research, non-commercial only**; a commercial deployment must switch to an Apache-2.0 model or Claude | Qwen2.5-1.5B (5% cited), Qwen2.5-7B 4-bit (same quality, twice as slow, fills the GPU), fine-tuning facts into a model (goes stale with every commit and cannot cite; PRD non-goal) |
| Known answers | Verified-answers table plus an in-memory matcher | Admin-approved answers are served without search or generation when a new question is within 0.91 cosine of an approved question, mentions no code name the approved question lacks, and none of the cited files changed since approval | Serving unreviewed model answers from a cache (no human check), a lower threshold (the near-miss set produces false matches below 0.90) |
| Frontend | Next.js 16 (App Router) + Tailwind | TypeScript and fast iteration. A route handler (`src/app/api/[...path]`) is the backend-for-frontend: the browser only talks to it, and it adds a **regular** API key server-side. `/api/admin/*` is forwarded only with the admin's own key from an HttpOnly, SameSite=Strict cookie set by `/api/admin-session` | Plain React SPA; a `NEXT_PUBLIC_` key (would ship in the JavaScript bundle) |
| Containerization | Docker: `docker/backend.Dockerfile`, `frontend/Dockerfile`, `docker/docker-compose.yml` | Standard and portable; matches the Azure target. The backend image installs CPU PyTorch | — |
| CI | GitHub Actions (`.github/workflows/ci.yml`) | Ruff, pytest, frontend lint/type-check/build, then image build and push to GHCR | — |
| Deploy targets | GitHub (source), Hugging Face Spaces (public demo), Azure Container Apps (production target) | HF is the free demo link; Azure is the enterprise story the target roles name | Self-managed VM or bare Kubernetes as a first step |

## 4. Non-functional requirements

All figures were measured on the dev machine (RTX 4060 Laptop, 8 GB, CUDA PyTorch `2.12.0+cu130`) and are single-user numbers, not load tests.

- **Retrieval latency:** about 0.8-0.9 s per question in steady state over 146,435 chunks. The first question after start-up is slower (warm-up). BM25 scoring over every chunk is the largest part.
- **Generation latency:** Qwen2.5-3B fp16, roughly 8-15 s per answer. It was 50-60 s for the 1.5B on a CPU-only PyTorch build.
- **Verified answers:** returned without generation; the match takes the time of one question embedding plus one matrix product.
- **Start-up:** about 70 s (embedding model, keyword and symbol index over 146,435 chunks, and the 3B on the GPU).
- **GPU memory:** about 7.2 of 8.2 GB with the 3B and the embedder loaded. Local generation is serialized: one request at a time, so background drafting cannot overflow the card.
- **Sync:** a no-change run over 7,546 files takes about 5 s. A full build of the corpus embeds 146k chunks in roughly 20 minutes on this GPU.
- **Throughput and availability:** not design targets for this single-user deployment.

## 5. Security requirements

- Secrets are never committed: `.env` and `frontend/.env.local` are gitignored.
- CORS: an explicit, environment-controlled origin list, no credentials, GET/POST/DELETE and two headers only.
- Auth: every route except `/health` requires `X-API-Key`. Keys are stored as SHA-256 hashes and shown once. `/admin/*` (dashboard, sync, verified answers, keys, stats) accepts only the bootstrap `SENTINEL_API_KEY`. The frontend's own key is a regular key without admin rights.
- Admin sessions in the browser: an HttpOnly, SameSite=Strict cookie (Secure in production), 8 hours. The proxy never forwards `/admin/*` with the server key.
- Input validation: Pydantic length and range limits on every request field. Uploads are capped at 10 MB, extension allow-listed, and stripped of path components.
- Verified answers are served only after an admin approves them, and approval requires at least one valid `[S#]` citation.

## 6. Constraints

- **Two runtimes must keep working:** the CUDA dev machine and CPU-only containers. Test every model-loading change on both. The container is CPU-only, so its realistic answer path is Claude; the local 3B on CPU is too slow for interactive use.
- **Single writer to the index.** ChromaDB and the in-memory keyword index are owned by one process. Run the sync through `POST /admin/sync` while the API is up, and the CLI only while it is down.
- **ChromaDB has no horizontal scaling.** Fine for one machine; migrate when that stops being true.

## 7. Open technical risks

- The Claude path has not run against the real API (no key available).
- The Docker images and the CI workflow have not been run yet.
- Retrieval misses 13 of 40 eval questions in the top 5.
- Verified-answer matching recognises only 45% of paraphrases at a threshold that allows no false matches.
- The keyword index lives in RAM and is rebuilt after uploads and syncs that change files.
