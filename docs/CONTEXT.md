# SENTINEL — Enterprise RAG Pipeline: Full Project Context

> Upload this file at the start of every Claude chat session.
> This is the single source of truth for the project. Every rule here is mandatory.

---

## 1. WHO YOU ARE IN THIS SESSION

You are a **Senior RAG Engineer** with 12+ years of experience building retrieval-augmented generation systems for enterprises including large-scale search and AI assistant products. You have deep expertise in:

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

**Project Name:** Sentinel

**Purpose:** An enterprise-grade open chatbot that lets users ask natural language questions over a large codebase and documentation set. It retrieves relevant source code and docs, assembles context, and generates a grounded answer using an LLM. Every answer cites the exact source files it came from.

**Current Domain:** Apache Superset codebase (Python, TypeScript, Markdown docs). This is the first integration. The pipeline must be designed to support any enterprise document source in the future.

**Goal:** A fully operational end-to-end RAG pipeline with:
- Document ingestion (initial bulk + incremental uploads)
- Intelligent chunking
- Vector + keyword hybrid search
- Cross-encoder re-ranking
- LLM answer generation (grounded, cited, no hallucination)
- Streaming API
- Conversational memory (multi-turn)
- React chat UI
- Authentication
- Observability

---

## 3. CURRENT TECH STACK

| Layer | Technology |
|---|---|
| Backend API | FastAPI (Python 3.10) |
| Vector Store | ChromaDB (persistent, local) |
| Embedding Model | `sentence-transformers/all-MiniLM-L6-v2` (384 dims) |
| LLM | `Qwen/Qwen2.5-1.5B-Instruct` (local, HuggingFace) |
| Frontend | Next.js 15 + Tailwind CSS (React, TypeScript) |
| Containerization | Docker |
| Data Format | JSONL (chunks), ChromaDB binary (index) |
| Dependencies | fastapi, uvicorn, chromadb, sentence-transformers, transformers, accelerate, torch, pydantic, tqdm |

---

## 4. COMPLETE FILE STRUCTURE (CURRENT STATE)

```
sentinel_project/
├── .gitignore
├── Dockerfile
├── requirements.txt
├── README.md
│
├── backend/
│   └── app/
│       ├── __init__.py
│       └── main.py                  ← FastAPI app, routes, Pydantic models
│
├── ingestion/
│   ├── __init__.py
│   ├── config.py                    ← Paths, supported extensions, excluded dirs
│   ├── records.py                   ← SourceRecord dataclass
│   ├── file_scanner.py              ← Walks filesystem, filters by extension
│   ├── loader.py                    ← Reads files, creates SourceRecord objects
│   ├── chunker.py                   ← Splits content into ChunkRecords, saves JSONL
│   ├── build_vectorstore.py         ← Embeds chunks, upserts into ChromaDB
│   ├── retriever.py                 ← Queries ChromaDB, returns top-k results
│   ├── rag_service.py               ← LLM loading, prompt building, answer generation
│   └── rag_engine.py                ← OLD version (broken, not imported, to be removed)
│
├── data/
│   ├── processed/
│   │   └── chunks.jsonl             ← Pre-processed chunks (should NOT be in git)
│   └── indexes/
│       └── chroma/                  ← ChromaDB binary index (should NOT be in git)
│
└── frontend/
    ├── package.json
    ├── next.config.ts
    ├── src/
    │   └── app/
    │       ├── layout.tsx
    │       ├── globals.css
    │       └── page.tsx             ← Chat UI (question input, answer display, sources)
    └── public/
```

---

## 5. WHAT EACH FILE DOES (CURRENT IMPLEMENTATION)

### `ingestion/config.py`
Defines the Superset repo path (`workspace/superset`), supported file extensions (`.py`, `.md`, `.mdx`, `.js`, `.jsx`, `.ts`, `.tsx`), and directories to exclude (`node_modules`, `.git`, `__pycache__`, etc.).

### `ingestion/records.py`
Defines `SourceRecord` dataclass: `source_id` (UUID), `source_type`, `path`, `language`, `title`, `content`.

### `ingestion/file_scanner.py`
Recursively walks the Superset repo path. Skips excluded directories and unsupported file extensions. Returns a list of `Path` objects.

### `ingestion/loader.py`
Reads each file as UTF-8 text. Creates a `SourceRecord` per file. Generates a **fresh UUID** per run (this is a bug — causes duplicate embeddings on re-index, not content-hashed).

### `ingestion/chunker.py`
Two strategies:
- **Markdown:** regex split on headers (`^#{1,6} `), one section per chunk
- **Code/other:** sliding window of 80 lines with 15-line overlap

Produces `ChunkRecord` dataclass. Saves to `data/processed/chunks.jsonl`.

**Known weakness:** Line-based code chunking is not semantically aware. It cuts through function bodies.

### `ingestion/build_vectorstore.py`
Loads `chunks.jsonl`. Embeds with `all-MiniLM-L6-v2` in batches of 64. Upserts into ChromaDB collection named `superset_codebase`. Stores metadata: `source_id`, `source_type`, `path`, `language`, `title`, `chunk_index`.

### `ingestion/retriever.py`
**Critical bug:** Instantiates `SentenceTransformer` on every single query call (takes 2-3 seconds each time). Must be a singleton.

Encodes the query, queries ChromaDB with cosine similarity, returns top-k as list of dicts with `id`, `content`, `metadata`, `distance`.

### `ingestion/rag_service.py`
Module-level singletons `_tokenizer` and `_model` for Qwen 2.5-1.5B. `load_llm()` implements lazy loading with guard (correct pattern).

`build_prompt()` assembles context blocks with `[S1]`, `[S2]` citation markers. Instructs the model not to use outside knowledge and to cite sources explicitly.

`generate_text()` runs inference. Extracts the `ANSWER:` section from output.

`ask_sentinel()` orchestrates: retrieve → build prompt → generate → format sources → return dict.

**Known weakness:** Model loaded without `dtype=torch.float16` or `device_map="auto"`. No quantization.

### `backend/app/main.py`
**Critical bug on line 67-71:** `/query` endpoint calls `ask_sentinel()` and assigns to `result` but **never returns it**. Every call returns a 500 error.

**Dead code on line 92:** `return result` is inside `search()` after a `return` statement. Unreachable. `result` is not even defined in `search()` scope.

Defines: `QueryRequest`, `SourceItem`, `QueryResponse` Pydantic models.
Routes: `GET /`, `GET /health`, `POST /query` (broken), `POST /search`.
CORS: allows `localhost:3000` and `127.0.0.1:3000`.

### `backend/app/main.py` — unused import
`from typing import Any` imported at line 26, mid-file, never used.

### `frontend/src/app/page.tsx`
React client component. State: `question`, `result`, `loading`, `error`.

**Bug:** `error` state is set on failure but never rendered in JSX. Users see no error message when API fails.

**Bug:** API URL hardcoded to `http://127.0.0.1:8000/query`. Dockerfile exposes port 7860. Mismatch breaks Docker deployment.

**Debug artifact:** `console.log("Ask button clicked")` left in onClick handler.

`top_k` is hardcoded to `3` in the fetch call (not configurable by user).

### `ingestion/rag_engine.py`
**Dead file.** No longer imported anywhere. Contains `NameError`: references `MODEL_NAME` which is undefined (only `MODEL_ID` is defined). To be deleted.

### `Dockerfile`
Runs backend on port 7860. Copies `backend/`, `ingestion/`, `data/`. Does not copy `frontend/` (frontend runs separately).

### `.gitignore`
**Security bug:** `.env` was removed from `.gitignore`. Secrets can now be accidentally committed.
**Data bug:** `data/indexes/` and `data/processed/chunks.jsonl` were removed. Binary ChromaDB files are now tracked in git (bloat).

---

## 6. CURRENT BUGS — MUST FIX BEFORE ANYTHING ELSE

These must be resolved immediately. Do not add new features until these are fixed.

| # | File | Line | Bug | Fix |
|---|---|---|---|---|
| 1 | `backend/app/main.py` | 67 | `/query` never returns `result` → HTTP 500 on every call | Add `return result` after `ask_sentinel()` call |
| 2 | `backend/app/main.py` | 92 | `return result` dead code in `search()`, wrong scope | Delete this line |
| 3 | `ingestion/retriever.py` | 16 | `SentenceTransformer` loaded on every query | Move to module-level singleton, load once at startup |
| 4 | `ingestion/rag_service.py` | 21 | Model loaded without `float16` or `device_map` | Add `torch_dtype=torch.float16`, `device_map="auto"` |
| 5 | `frontend/src/app/page.tsx` | 26 | `error` state never rendered | Add error display block in JSX |
| 6 | `frontend/src/app/page.tsx` | 34 | Port 8000 hardcoded, Dockerfile uses 7860 | Use environment variable for API base URL |
| 7 | `.gitignore` | — | `.env` missing | Add `.env` back |
| 8 | `.gitignore` | — | Binary data files tracked | Add `data/indexes/` and `data/processed/` back |
| 9 | `ingestion/rag_engine.py` | 14 | `MODEL_NAME` undefined (`NameError`) | Delete this file entirely |
| 10 | `backend/app/main.py` | 26 | Unused `from typing import Any` mid-file | Remove |

---

## 7. THE COMPLETE END-TO-END PIPELINE (TARGET STATE)

This is the full architecture this project must become. Stages marked `[DONE]` exist in working form. `[PARTIAL]` means started but broken or incomplete. `[TODO]` means not built yet.

```
┌─────────────────────────────────────────────────────────────────┐
│                    DOCUMENT INGESTION LAYER                     │
│                                                                 │
│  [DONE]    File Scanner     → walks directories, filters exts  │
│  [DONE]    File Loader      → reads UTF-8, creates records      │
│  [TODO]    PDF Loader       → extract text from .pdf            │
│  [TODO]    DOCX Loader      → extract text from .docx           │
│  [TODO]    HTML Loader      → strip tags, extract prose         │
│  [TODO]    Upload API       → POST /documents/upload endpoint   │
│  [TODO]    File Hash Check  → SHA-256, skip unchanged files     │
│  [TODO]    Background Queue → Celery/RQ, non-blocking uploads   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      CHUNKING LAYER                             │
│                                                                 │
│  [PARTIAL] Markdown Split   → header-based (works but no size  │
│                               limit per chunk)                 │
│  [PARTIAL] Code Split       → line-window (semantically naive) │
│  [TODO]    AST Chunker      → Python: split at function/class  │
│                               boundaries using `ast` module    │
│  [TODO]    Token-aware Size → chunk size in tokens (512-1024)  │
│                               not lines                        │
│  [TODO]    Semantic Overlap → overlap on complete sentences,   │
│                               not arbitrary line count         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      EMBEDDING LAYER                            │
│                                                                 │
│  [PARTIAL] Embedding Model  → all-MiniLM-L6-v2 (too small)    │
│  [TODO]    Upgrade Model    → BAAI/bge-large-en-v1.5 (1024d)  │
│                               or text-embedding-3-small (API)  │
│  [PARTIAL] Batch Embedding  → batched (correct), but model     │
│                               reloads each query in retriever  │
│  [TODO]    Singleton Load   → load embedding model ONCE at     │
│                               app startup, reuse every query   │
│  [DONE]    ChromaDB Upsert  → idempotent upsert with batch    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      RETRIEVAL LAYER                            │
│                                                                 │
│  [PARTIAL] Vector Search    → ChromaDB cosine similarity       │
│  [TODO]    BM25 Index       → keyword search alongside vector  │
│  [TODO]    Hybrid Fusion    → Reciprocal Rank Fusion (RRF)     │
│                               combines vector + BM25 scores    │
│  [TODO]    Metadata Filter  → filter by language, path prefix, │
│                               file type before vector search   │
│  [TODO]    Cross-Encoder    → re-rank top-20 to pick best 5    │
│            Re-ranking         using cross-encoder/ms-marco     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    LLM GENERATION LAYER                         │
│                                                                 │
│  [PARTIAL] Prompt Building  → citation format [S1][S2] good,   │
│                               but model too small to follow it │
│  [PARTIAL] Local LLM        → Qwen 1.5B (too small, no GPU    │
│                               optimization)                    │
│  [TODO]    LLM Upgrade      → Option A: API (Claude Haiku /   │
│                               GPT-4o-mini) — recommended       │
│                               Option B: Qwen 7B 4-bit quant   │
│  [TODO]    Streaming Output → StreamingResponse / SSE so user  │
│                               sees text as it generates        │
│  [TODO]    Token Budget     → enforce max context tokens,      │
│                               truncate chunks if needed        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      SESSION & MEMORY LAYER                     │
│                                                                 │
│  [TODO]    Session Store    → Redis or SQLite per-session      │
│  [TODO]    Conversation     → store last N turns in session    │
│            History            pass to LLM as prior context     │
│  [TODO]    Query Reform.    → rewrite follow-up questions to   │
│                               be self-contained before embed   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        API LAYER                                │
│                                                                 │
│  [DONE]    GET  /           → service info                     │
│  [DONE]    GET  /health     → health check                     │
│  [BROKEN]  POST /query      → RAG answer (missing return)      │
│  [DONE]    POST /search     → retrieval only (no LLM)          │
│  [TODO]    POST /documents/upload  → ingest new file           │
│  [TODO]    GET  /documents         → list indexed documents    │
│  [TODO]    DELETE /documents/{id}  → remove from index         │
│  [TODO]    GET  /query/stream      → SSE streaming response    │
│  [TODO]    POST /sessions          → create conversation       │
│  [TODO]    GET  /sessions/{id}     → get session history       │
│  [TODO]    Auth Middleware  → API key header validation        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      FRONTEND LAYER                             │
│                                                                 │
│  [PARTIAL] Question Input   → textarea, submit button          │
│  [PARTIAL] Answer Display   → shows answer text                │
│  [PARTIAL] Source Cards     → shows source metadata + preview  │
│  [TODO]    Chat Thread View → full conversation history UI     │
│  [TODO]    Streaming Render → stream tokens as they arrive     │
│  [TODO]    Error Display    → show error messages to user      │
│  [TODO]    File Upload UI   → drag-and-drop document upload    │
│  [TODO]    Configurable K   → let user choose top_k            │
│  [TODO]    Env-based URL    → NEXT_PUBLIC_API_URL env var      │
│  [TODO]    Feedback Buttons → thumbs up/down per answer        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    OBSERVABILITY LAYER                          │
│                                                                 │
│  [TODO]    Query Logging    → log every query + retrieved IDs  │
│  [TODO]    Latency Tracking → retrieval ms, generation ms      │
│  [TODO]    Feedback Store   → persist thumbs up/down signals   │
│  [TODO]    Eval Suite       → fixed Q&A pairs, measure quality │
└─────────────────────────────────────────────────────────────────┘
```

---

## 8. RULES — MANDATORY, NO EXCEPTIONS

These apply to every code change in every session. Never violate these.

### 8.1 Architecture Rules

- **Never hardcode file paths.** All paths must come from `config.py` or environment variables. The Superset path is only a default — the pipeline must work with any document source.
- **Never instantiate heavy objects (models, DB clients) inside request handlers.** All models and connections must be module-level singletons, loaded once at application startup.
- **Never block the API on ingestion.** Document upload and processing must run in a background task (FastAPI `BackgroundTasks` minimum, Celery for production). The upload endpoint must respond immediately with a job ID.
- **Always use upsert, never insert.** Every write to ChromaDB must use `upsert()` so re-indexing is idempotent and does not create duplicates.
- **Content hash before embed.** Before processing any file, compute its SHA-256 hash and compare to stored hash. Skip embedding if unchanged.

### 8.2 Code Quality Rules

- **No comments explaining what the code does.** Code must be self-explanatory through naming. Only add a comment when the WHY is non-obvious (a workaround, a hidden constraint, a subtle invariant).
- **No unused imports.** Remove them immediately.
- **No dead code.** Deleted behavior stays deleted. No commented-out blocks.
- **No mid-file imports.** All imports at the top of the file, stdlib → third-party → local.
- **No print statements in production code.** Use `logging` module with proper log levels.
- **Pydantic models for all API request and response shapes.** Never return raw dicts from route handlers.
- **Every FastAPI route handler must have a return statement.** This is a critical failure mode — always verify.

### 8.3 Security Rules

- **`.env` must always be in `.gitignore`.** Never commit secrets, API keys, model tokens, or database credentials.
- **`data/indexes/` and `data/processed/` must always be in `.gitignore`.** Binary database files and large JSONL data must not be tracked in git.
- **No CORS wildcard (`allow_origins=["*"]`) in production.** CORS origins must be explicit and environment-controlled.
- **All API endpoints except `/health` must be protected by authentication** once auth is implemented. Do not add new routes without adding them to the auth middleware.
- **Validate all user input at API boundaries.** `min_length`, `max_length`, `ge`, `le` constraints on all Pydantic fields. Never pass raw user input to the filesystem or shell.

### 8.4 Chunking Rules

- **Chunk size must be measured in tokens, not lines or characters.** Target 512 tokens per chunk, maximum 1024. Use `tiktoken` or the tokenizer's `encode()` to count.
- **Code files must be chunked at semantic boundaries.** Python: use the `ast` module to detect function and class boundaries. Never cut through a function body.
- **Every chunk must contain enough standalone context to be retrievable.** A chunk that starts mid-sentence or mid-function is a retrieval failure waiting to happen.
- **Overlap must be meaningful.** Overlap should include the complete last sentence or the complete function signature of the previous chunk, not a fixed number of arbitrary lines.

### 8.5 Retrieval Rules

- **Never reload the embedding model per query.** The model must be loaded once and reused. Violating this will make the API unusably slow.
- **Always normalize embeddings** (`normalize_embeddings=True`). Cosine similarity only works correctly on unit-normalized vectors.
- **Retrieve more than you return.** Retrieve top-20, re-rank, return top-5. Never retrieve exactly the number you return — re-ranking requires a larger candidate pool.
- **Log what was retrieved for every query.** You cannot debug retrieval quality without knowing what the retriever returned.

### 8.6 LLM Rules

- **The LLM must never answer from outside knowledge.** The prompt must explicitly forbid this. The system is grounded-only.
- **Every factual claim in the answer must cite a source using `[S1]`, `[S2]`, etc.** Uncited statements are hallucinations from the model's weights, not from retrieved context.
- **Max new tokens must be bounded.** Never allow unbounded generation. Set `max_new_tokens` to a value appropriate for the expected answer length (300-500 for most queries).
- **Enforce a token budget for context.** If retrieved chunks exceed the model's context window, trim the least-relevant chunks. Never silently truncate mid-chunk.
- **If using a local model, always load with quantization on GPU.** Minimum: `torch_dtype=torch.float16`. Preferred: 4-bit quantization with `bitsandbytes` for models 7B+.

### 8.7 Frontend Rules

- **The API base URL must come from `NEXT_PUBLIC_API_URL` environment variable.** Never hardcode `localhost:8000` or any port.
- **Every error state must be rendered to the user.** If `error` state is set, the user must see it. Silent failures are not acceptable.
- **Remove all `console.log` debug statements before considering any feature complete.**
- **The loading state must be accurate.** Disable inputs while a request is in flight. Re-enable on both success and error (use `finally`).
- **Streaming responses must be handled with SSE or chunked fetch.** Do not wait for the full LLM response before rendering.

### 8.8 Git Rules

- **Never commit binary files or large data files.** ChromaDB index files, `chunks.jsonl`, model weights, and `.env` files must never appear in a commit.
- **Never force-push to main.**
- **Commit messages must describe why, not what.** "Fix missing return in /query endpoint causing 500 on every request" not "fix bug".

---

## 9. PRIORITY ROADMAP

Work strictly in this order. Do not skip phases.

### Phase 1 — Fix What's Broken (Do First, No Exceptions)
1. Add `return result` to `/query` endpoint (`backend/app/main.py:72`)
2. Delete dead `return result` from `search()` (`backend/app/main.py:92`)
3. Move `SentenceTransformer` to module-level singleton in `retriever.py`
4. Add `torch_dtype=torch.float16, device_map="auto"` to model load in `rag_service.py`
5. Render `error` state in `page.tsx`
6. Replace hardcoded port 8000 with `NEXT_PUBLIC_API_URL` env var in `page.tsx`
7. Add `.env`, `data/indexes/`, `data/processed/` back to `.gitignore`
8. Delete `ingestion/rag_engine.py` (broken dead code)
9. Remove unused `from typing import Any` from `main.py`
10. Remove `console.log` from button handler in `page.tsx`

### Phase 2 — Chunking Upgrade
1. Implement AST-aware Python chunker using `ast.parse()`, split at function/class boundaries
2. Add token counting to enforce 512-token max chunk size
3. Implement token-aware overlap (include complete last sentence)
4. Add chunk size validation — reject chunks under 20 tokens as noise

### Phase 3 — Retrieval Upgrade
1. Add BM25 index alongside ChromaDB (use `rank_bm25` library)
2. Implement Reciprocal Rank Fusion to merge vector + BM25 results
3. Add cross-encoder re-ranking (`cross-encoder/ms-marco-MiniLM-L-6-v2`)
4. Add metadata pre-filter support (by language, path prefix)

### Phase 4 — Ingestion API
1. Implement `POST /documents/upload` (multipart, accepts .py .md .pdf .docx .txt)
2. Add PDF text extraction (`pymupdf` or `pdfplumber`)
3. Add DOCX extraction (`python-docx`)
4. Add SHA-256 file hashing, skip unchanged files
5. Background processing with FastAPI `BackgroundTasks`
6. `GET /documents` — list all indexed source paths
7. `DELETE /documents/{id}` — delete from ChromaDB by source_id

### Phase 5 — LLM Upgrade
1. Add `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` env var support
2. Implement API-based generation path (Claude Haiku or GPT-4o-mini) as primary
3. Keep local Qwen as fallback (with proper quantization)
4. Add `StreamingResponse` endpoint (`GET /query/stream`) using SSE
5. Implement token budget enforcement — trim context if over limit

### Phase 6 — Conversation Memory
1. Add Redis (or SQLite) session store
2. `POST /sessions` — create session, return session_id
3. Store last 10 turns per session
4. Query reformulation: rewrite follow-up questions to be self-contained before embedding
5. Pass conversation history into LLM prompt

### Phase 7 — Authentication
1. API key validation middleware
2. `X-API-Key` header required on all routes except `/health`
3. Key management: generate, revoke, list (simple admin endpoint)

### Phase 8 — Frontend Upgrade
1. Chat thread UI (replace single Q&A with message history)
2. Streaming token render (SSE consumer)
3. File upload drag-and-drop
4. Top-k slider (configurable by user, 1–15)
5. Feedback buttons (thumbs up/down) per answer
6. Error toast notifications

### Phase 9 — Observability
1. Structured JSON logging for every query (query, retrieved_ids, latency_ms, model)
2. Feedback persistence (store thumbs up/down to SQLite)
3. Evaluation suite: fixed set of 50 Q&A pairs, script to measure answer quality
4. Dashboard showing query volume, avg latency, feedback ratio

---

## 10. DECISION LOG (DO NOT OVERRIDE WITHOUT REASON)

| Decision | Chosen | Reason |
|---|---|---|
| Vector DB | ChromaDB | Local, no external service, good for development. Migrate to Qdrant when scaling. |
| Embedding model | all-MiniLM-L6-v2 (upgrade to bge-large) | Fast, local, no API cost. Upgrade path defined. |
| LLM | API-first (Claude Haiku), local Qwen as fallback | Answer quality matters more than inference cost at this stage. |
| Chunking unit | Tokens (not lines) | Lines vary wildly in length. Tokens are what the model actually sees. |
| API framework | FastAPI | Async support, auto-docs, Pydantic native, standard choice. |
| Frontend | Next.js 15 + Tailwind | TypeScript, App Router, easy API routes, Tailwind utility-first. |
| Hybrid search | Vector + BM25, fused with RRF | Vector alone misses exact keyword matches. Hybrid is the standard for code search. |
| Re-ranking | Cross-encoder (ms-marco) | Bi-encoder retrieval is recall-optimized; cross-encoder re-ranking adds precision. |

---

## 11. CONTEXT THAT MUST BE CARRIED INTO EVERY SESSION

- The user is building this project actively. They want concrete, actionable guidance — not theoretical overviews.
- The project is at the end of Phase 1 setup. Phase 1 bugs are not yet fixed.
- The domain is Apache Superset today. The architecture must generalize to any enterprise document corpus.
- Quality of answers (no hallucination, correct citations) is more important than response speed at this stage.
- The pipeline must handle both bulk initial indexing and incremental document uploads without a full rebuild.
- Any suggestion to "just use LangChain" or "just add LlamaIndex" should be accompanied by a clear justification. The current architecture is custom and that is intentional — the user is learning the internals.
- When asked to write code, always write the full implementation, not pseudocode or placeholders. If a file needs to change, show the full changed file or the exact edit.
- When a bug exists in current code, fix it before adding new features.

---

*Last updated: 2026-06-16 | Model context: Claude Sonnet 4.6*

---

## 12. STRUCTURE UPDATE LOG

**2026-08-21** — Reorganized project layout for clarity, no application logic changed:
- `SENTINEL_PROJECT_CONTEXT.md` moved to `docs/CONTEXT.md` (this file)
- Added `docs/SENIOR_REVIEW.md` — a senior-engineer-style review and prioritized roadmap
- `Dockerfile` moved to `docker/backend.Dockerfile`; added `docker/docker-compose.yml`
- Added root `CLAUDE.md` pointing at this file, so it auto-loads instead of being pasted in manually each session
- Added `.env.example`
- Added `eval/` placeholder for Phase 9 evaluation work
- Fixed `.gitignore`: added `.env`, `data/indexes/`, `data/processed/`, `_to_delete/` (bug #7 and #8 from section 6 above — still needs the corresponding code fixes, this only fixes the ignore rules)
- Removed an empty unused `vectorstore/` folder, stale `__pycache__/` folders, and a `.claude/settings.json` that had a live API key hardcoded in it instead of real settings (moved to a local `_to_delete/` folder, not deleted outright — rotate that key)

Section 4's file tree above still reflects the pre-reorg layout for the `backend/`, `ingestion/`, `frontend/`, and `data/` internals, which are unchanged. See the root `README.md` for the current top-level layout.
