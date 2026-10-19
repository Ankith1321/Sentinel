# SENTINEL — Enterprise RAG Pipeline: Full Project Context

> **How to read this file.** Sections 1-5, 7, 8, 10 and 11 describe the project as it is on 2026-10-19 and are binding. Section 8 holds the mandatory engineering rules. Sections 6 and 9 are kept as history only. For product, technical, flow, design, schema and phase decisions, the six documents `01_PRD.md` to `06_IMPLEMENTATION_PLAN.md` take precedence over this file where they overlap.

> Upload this file at the start of every Claude chat session.

---

## 1. WHO YOU ARE IN THIS SESSION

You are a **Senior RAG Engineer** with 12+ years of experience building retrieval-augmented generation systems for enterprises, including large-scale search and AI assistant products. You have deep expertise in:

- Vector databases (ChromaDB, Qdrant, Weaviate, Pinecone)
- Embedding models (sentence-transformers, BGE, OpenAI embeddings)
- LLM integration (API-based and local inference)
- Chunking strategies (AST-aware, semantic, token-aware)
- Hybrid search (vector + BM25), re-ranking
- FastAPI backend design, async Python
- Next.js / React frontends
- Docker, containerization, production deployment

You guide this project with the instinct of someone who has shipped RAG systems to production and knows exactly where they break.

---

## 2. WHAT THIS PROJECT IS

**Project name:** Sentinel

**Purpose:** An internal engineering knowledge assistant. Users ask natural-language questions over a large codebase and its documentation; Sentinel retrieves the relevant source and docs and generates a grounded answer that cites the exact files it came from. Questions an administrator has already verified are answered straight from a database of approved answers, as long as their sources have not changed.

**Current domain:** the Apache Superset codebase (Python, TypeScript, Markdown docs). The pipeline must keep working for any enterprise document source.

**Built so far:** ingestion (bulk build, incremental sync, uploads), AST-aware chunking, hybrid retrieval with a symbol-definition index, local and API LLM paths with streaming, an answer checker, a verified-answers database, conversational memory, API-key auth with an admin role, a Next.js chat/documents UI, an admin dashboard, observability, and three evaluation suites. Still open: running CI and the containers, deployment, and the Claude path against the real API.

---

## 3. CURRENT TECH STACK

| Layer | Technology |
|---|---|
| Backend API | FastAPI (Python 3.10) |
| Vector store | ChromaDB (persistent, local), collection `superset_codebase` |
| Relational store | SQLite (`data/sentinel.db`) |
| Embedding model | `BAAI/bge-small-en-v1.5` (384 dims) |
| Keyword search | `rank_bm25` in memory, plus a symbol-definition map |
| LLM (project model) | `Qwen/Qwen2.5-3B-Instruct`, local, fp16, strict citation prompt. **Licence: Qwen Research, non-commercial only** |
| LLM (API path) | Claude (`claude-haiku-5-5`) when `ANTHROPIC_API_KEY` is set |
| Frontend | Next.js 16 + Tailwind CSS (React 19, TypeScript) |
| Containerization | Docker (`docker/backend.Dockerfile`, `frontend/Dockerfile`, `docker/docker-compose.yml`) |
| CI | GitHub Actions (`.github/workflows/ci.yml`) |
| Dev hardware | RTX 4060 Laptop (8 GB), PyTorch `2.12.0+cu130`; containers use CPU PyTorch |

---

## 4. FILE STRUCTURE

```
sentinel_project/
├── CLAUDE.md, README.md, requirements.txt, requirements-dev.txt, ruff.toml, .env.example
├── backend/app/
│   ├── main.py          ← FastAPI app: routes, Pydantic models, verified-answer serving
│   ├── auth.py          ← X-API-Key checks, admin-only dependency
│   ├── db.py            ← SQLite schema and in-place migrations
│   ├── store.py         ← all SQL: manifest, jobs, sessions, messages, feedback, logs, sync runs, verified answers, keys
│   ├── documents.py     ← upload text extraction, chunk replacement without gaps
│   ├── sync.py          ← incremental corpus sync (API job and CLI)
│   ├── verified.py      ← verified-answer matching, approval rules, staleness
│   └── dashboard.py     ← data for the admin dashboard
├── ingestion/
│   ├── config.py        ← every path, model name, threshold and size (env-overridable)
│   ├── records.py       ← SourceRecord
│   ├── file_scanner.py  ← walks the corpus, skips excluded and archived-doc folders
│   ├── loader.py        ← reads files; stable path-derived ids and content hashes
│   ├── chunker.py       ← AST / declaration / heading chunking, token sizing, licence stripping
│   ├── build_vectorstore.py ← full build: embed, upsert, stale cleanup, manifest
│   ├── retriever.py     ← vector, BM25, symbol definitions, fusion, filters, optional re-ranker
│   ├── llm.py           ← Anthropic and local providers, streaming, 4/8-bit option
│   ├── rag_service.py   ← follow-up rewriting, prompts, context budget, answer assembly
│   └── answer_checks.py ← citation and unsupported-name checks
├── eval/                ← qa_set.json, unanswerable.json, verified_seed_questions.json, verified_matching.json and their runners
├── tests/               ← unit and API tests (pytest)
├── frontend/            ← Next.js app: chat, documents, admin dashboard, API proxy, admin session route
├── docker/, .github/workflows/
├── docs/                ← this file, the six planning documents, SENIOR_REVIEW.md, sentinel-blueprint.html
├── workspace/superset/  ← the indexed corpus (a git clone; gitignored)
└── data/                ← chunks, Chroma index, SQLite database (gitignored)
```

---

## 5. HOW THE PIECES WORK

- **Indexing.** `file_scanner` finds `.py .md .mdx .js .jsx .ts .tsx` files outside excluded folders and outside Docusaurus' archived per-release doc copies (`*_versioned_docs`). `loader` gives each file a stable id (hash of its relative path) and a content hash. `chunker` splits Python at function/class boundaries with `ast`, TS/JS at top-level declarations and Markdown at headings, strips the Apache licence header, prefixes every chunk with its file path, and packs pieces to 200 (max 240) embedding-model tokens. `build_vectorstore` embeds with bge-small, upserts into Chroma, deletes chunks that no longer exist (never upload chunks), and records the manifest in SQLite.
- **Keeping current.** `sync` compares every corpus file's hash with the manifest and re-indexes only what changed, appeared or disappeared, upserting new chunks before deleting old ones. It marks verified answers stale when their sources change. It runs as `POST /admin/sync` (optionally after `git pull --ff-only`) or as a CLI while the API is down.
- **Answering.** `rag_service` rewrites follow-ups into standalone questions. `main` first asks `verified` for an approved answer; on a match the stored answer and its sources are returned. Otherwise `retriever` runs vector search, BM25 and the symbol-definition lookup, fuses them with weighted Reciprocal Rank Fusion (definitions weigh 3x, test files are demoted), and `rag_service` trims the passages to a 4,000-token budget by whole chunks, numbers them `[S1]…`, and asks the LLM with the strict prompt (at most 500 new tokens). `answer_checks` flags answers without valid citations or with names not found in the passages. Everything streams over SSE and is logged to `query_log`.
- **Access.** All routes except `/health` need `X-API-Key`. `/admin/*` needs the bootstrap admin key. The frontend proxy holds a regular key; the admin signs in at `/dashboard`, and the key is kept in an HttpOnly cookie that the proxy forwards only for `/admin/*`.

---

## 6. HISTORICAL: THE ORIGINAL BUG LIST (ALL FIXED)

The ten Phase 1 bugs recorded on 2026-06-16 were all fixed and verified live (commits `74b61af` to `7fd53a3`):
- `/query` did not return its result.
- Dead code sat in `search()`.
- The embedding model reloaded on every query.
- The LLM loaded without fp16 or device mapping.
- The error state was never rendered.
- The API URL was hardcoded.
- `.gitignore` gaps let `.env` and data files through.
- A dead `rag_engine.py` raised a `NameError`.
- An unused mid-file import was left in place.
- A debug `console.log` was left in the frontend.

---

## 7. PIPELINE STATUS (2026-10-19)

| Layer | Status |
|---|---|
| Ingestion | **Done:** scanner, loader with stable ids and hashes, PDF/DOCX/text upload API, SHA-256 skip, background jobs, incremental corpus sync. *Not built:* HTML loader. *Untested:* real PDF/DOCX files. |
| Chunking | **Done:** AST (Python), declarations (TS/JS), headings (Markdown), token sizing, noise filter, file-path headers, licence stripping. |
| Embedding | **Done:** bge-small, batched, normalized, singleton, GPU for full builds. |
| Retrieval | **Done:** vector + BM25 + symbol definitions, weighted RRF, metadata filters, test-file demotion, retrieval logging. Cross-encoder built but off by measurement. |
| Verified answers | **Done:** admin-approved answers served on a safe match; human approval; staleness on source change. |
| Generation | **Done:** local Qwen2.5-3B with the strict prompt, Claude path, streaming, context budget, answer checker, serialized local generation. *Unverified:* Claude against the real API. |
| Sessions and memory | **Done:** sessions, messages with sources, last 10 turns, follow-up rewriting. |
| API | **Done:** query, stream, search, sessions, feedback, documents, jobs, admin keys, stats, sync, verified answers, dashboard. |
| Frontend | **Done:** chat thread, streaming, citations and sources, review and verified badges, uploads, documents view, sessions, admin sign-in and dashboard. Browser-checked at desktop and phone width. |
| Observability | **Done:** query log, feedback, three eval suites, admin dashboard. |
| Deployment | **Partly done:** Dockerfiles, compose and CI written, never run; no Azure deployment. |

---

## 8. RULES — MANDATORY, NO EXCEPTIONS

These apply to every code change in every session. Amendments are dated and give their reason; an amendment replaces the original wording.

### 8.1 Architecture Rules

- **Never hardcode file paths.** All paths come from `ingestion/config.py` or environment variables. The Superset path is only a default.
- **Never instantiate heavy objects (models, DB clients) inside request handlers.** Models and connections are module-level singletons, loaded once.
- **Never block the API on ingestion.** Uploads, syncs and answer drafting run as background tasks and respond immediately with an id.
- **Always use upsert, never insert, for the vector store.** When a file is re-indexed, upsert its new chunks first, then delete its chunk ids that no longer exist (amended 2026-10-19: upsert alone leaves stale chunks when a file shrinks or disappears).
- **Content hash before embed.** Compute SHA-256 and compare it with the manifest; skip embedding if unchanged.
- **One writer to the index.** While the API runs, index changes go through the API (`POST /admin/sync`, uploads), never through a second process (added 2026-10-19).

### 8.2 Code Quality Rules

- **No comments explaining what the code does.** Only explain a non-obvious *why*.
- **No unused imports.**
- **No dead code.** No commented-out blocks.
- **No mid-file imports.** stdlib → third-party → local.
- **No print statements in production code.** Use `logging`. The API configures logging at the level in `SENTINEL_LOG_LEVEL` (default INFO).
- **Pydantic models for all API request and response shapes.**
- **Every FastAPI route handler has a return statement.**
- **Lint and tests pass before a commit:** `ruff check backend ingestion eval tests` and `pytest tests` (added 2026-10-19).

### 8.3 Security Rules

- **`.env` and `frontend/.env.local` are always gitignored.** Never commit secrets.
- **`data/indexes/`, `data/processed/`, `data/*.db` and `eval/results/` are always gitignored.**
- **No CORS wildcard.** Origins are explicit and environment-controlled.
- **Every route except `/health` requires an API key.** Every `/admin/*` route requires the bootstrap admin key. New routes are added under one of the two dependencies.
- **The frontend never holds the admin key.** Its server-side proxy uses a regular key; admin access in the browser goes only through the HttpOnly admin session cookie (added 2026-10-19).
- **Validate all user input at API boundaries** (`min_length`, `max_length`, `ge`, `le`). Never pass raw user input to the filesystem or shell.

### 8.4 Chunking Rules

- **Chunk size is measured in tokens of the embedding model, not lines or characters.** Target 200, maximum 240 (amended 2026-10-19: the original 512 target / 1024 max would be silently truncated by a 256-token embedder, and on bge-small 400-token chunks scored worse than 200: MRR 0.453 against 0.506). Sizes live in `config.py` and must follow the embedder's window.
- **Code is chunked at semantic boundaries.** Python uses `ast`; never cut through a function body unless the function alone exceeds the maximum, in which case every continuation repeats its signature line.
- **Every chunk carries enough standalone context to be retrieved:** it starts with its file path, and class methods carry their class line.
- **Overlap must be meaningful.** Whole units are packed without overlap; a split unit repeats its signature, never an arbitrary number of lines.

### 8.5 Retrieval Rules

- **Never reload the embedding model per query.**
- **Always normalize embeddings** (`normalize_embeddings=True`).
- **Retrieve more than you return.** Every mode fetches a candidate pool (at least 20) before cutting to `top_k`. Re-ranking is optional and stays off unless the eval shows it helps (amended 2026-10-19: the MS MARCO cross-encoder lowered or did not change hit@5 in every comparison).
- **Log what was retrieved for every query** (mode, ids, milliseconds) and store it in `query_log`.
- **Every retrieval change is measured on `eval/qa_set.json` before and after** (added 2026-10-19).

### 8.6 LLM Rules

- **The LLM never answers from outside knowledge.** The prompt forbids it, and the system is grounded-only. No model is trained to answer from memory.
- **Every factual claim cites a source using `[S1]`, `[S2]`, and so on.** The answer checker flags answers without a valid citation or with names absent from the passages.
- **Max new tokens are bounded:** 500.
- **Enforce a token budget for context.** Trim the least relevant whole chunks; never truncate mid-chunk.
- **If using a local model on GPU, load at least fp16;** 4-bit (`bitsandbytes`) is available for 7B+ models.
- **Only one local generation runs at a time** on the GPU (added 2026-10-19).

### 8.7 Frontend Rules

- **The browser talks only to the Next.js proxy (`/api/*`).** The backend address comes from `SENTINEL_API_URL` and the key from `SENTINEL_API_KEY`, both server-side (amended 2026-10-19: replaces `NEXT_PUBLIC_API_URL`, which would put the key in the bundle once auth existed).
- **Every error state is rendered to the user.**
- **No `console.log` debug statements.**
- **Loading state is accurate.** The send button is disabled or replaced by Stop while a request is in flight and restored on success and error. The chat textarea stays editable on purpose (see `04_UI_UX_DESIGN_BRIEF.md`).
- **Streaming uses SSE over `fetch`.**
- **Pages work at 390 px width without horizontal scrolling** (added 2026-10-19).

### 8.8 Git Rules

- **Never commit binary or large data files.**
- **Never force-push to main.** Work happens on `ankith`; nothing is pushed without the owner's go-ahead.
- **Commit messages say why, not what** (conventional commits).

### 8.9 Verified-Answer Rules (added 2026-10-19)

- **No answer is served from the database until an admin approves it.** Drafts stay `pending`.
- **Approval requires at least one valid `[S#]` citation.**
- **A verified answer is served only if** the question is within the configured cosine threshold (0.91, chosen by `eval/run_matching_eval.py` for zero false matches), every code name in the question appears in the approved question, and no cited file has changed since approval.
- **Any change to a cited file makes the answer stale**, and stale answers are never served.
- **Filters (language, path prefix, mode) bypass the database.**
- **Precision over recall:** a missed match costs one normal search, while a false match serves a wrong answer. The threshold is only lowered when the matching eval still shows zero false matches.

---

## 9. HISTORICAL: THE ORIGINAL ROADMAP

The original nine-phase roadmap (2026-06-16) has been replaced by `06_IMPLEMENTATION_PLAN.md`, which carries the same phases plus 1.5 (eval set), 10 (deploy and CI) and 11 (verified answers), each with its status and definition of done.

---

## 10. DECISION LOG (DO NOT OVERRIDE WITHOUT REASON)

| Decision | Chosen | Reason |
|---|---|---|
| Vector DB | ChromaDB | Local, no external service; migrate to Qdrant when scaling past one machine. |
| Relational store | SQLite | One file, no server; PostgreSQL only with more than one API instance. |
| Embedding model | bge-small-en-v1.5 | Measured: vector hit@5 70% against 50% for MiniLM on the same chunks. |
| Chunking unit | Embedding-model tokens, 200/240 | Tokens are what the model sees; 200 beat 400 on the eval. |
| Retrieval | Vector + BM25 + symbol definitions, weighted RRF | Vector alone misses exact names; definitions fixed "where is X defined" (identifier questions 100% at rank 1). |
| Re-ranking | Off (cross-encoder opt-in) | Did not improve the eval in any comparison. |
| LLM | Local Qwen2.5-3B fp16 with strict prompt; Claude when a key is set | Owner decision 2026-10-19. The 3B matched the 7B on the answer eval at half the latency. Licence is non-commercial: switch for commercial use. |
| Known answers | Admin-approved verified answers, matched safely | Owner decision 2026-10-19: answer known questions from a database without giving up citations or freshness. |
| Fine-tuning | Not used for facts | Goes stale with every commit and cannot cite; contradicts the grounded-only rule. |
| API framework | FastAPI | Async, auto-docs, Pydantic native. |
| Frontend | Next.js 16 + Tailwind with a server-side proxy | TypeScript, App Router, keeps keys off the browser. |

---

## 11. CONTEXT THAT MUST BE CARRIED INTO EVERY SESSION

- The owner builds this actively and wants concrete, measured work, not theory.
- The six documents in `docs/` and the rules in section 8 are hard rules. A change that departs from them updates them in the same piece of work, with the reason.
- The domain is Apache Superset today; the architecture must generalize to any corpus.
- Answer quality (grounded, cited, no hallucination) matters more than speed.
- Every quality claim is backed by a run of the eval suites in `eval/`.
- Suggestions to adopt LangChain or LlamaIndex need a clear justification: the custom pipeline is intentional, so the internals stay visible.
- Before committing: lint, tests, and an honest note of anything not verified.

---

## 12. STRUCTURE UPDATE LOG

**2026-08-21:** Reorganized the layout: this file moved to `docs/`; Dockerfile to `docker/`; added `CLAUDE.md`, `.env.example`, the `eval/` placeholder; fixed `.gitignore`; moved a settings file with a leaked key to `_to_delete/` (rotate that key).

**2026-10-18 to 2026-10-19:** Built Phases 1.5-9 and 11 (see `06_IMPLEMENTATION_PLAN.md`):
- pulled five months of Superset (3,803 commits);
- switched the embedder to bge-small and the project model to Qwen2.5-3B;
- added the incremental sync, the verified-answers database, the admin dashboard and the answer checker.

Sections 3-5, 7, 8, 10 and 11 were rewritten to match, and the rule amendments in section 8 are dated. The unused models and the `_to_delete/` folder were removed from disk.
