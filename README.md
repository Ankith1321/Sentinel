# Sentinel

An internal engineering knowledge assistant. Ask natural-language questions about a large, mixed-language codebase (currently Apache Superset: Python, TypeScript, Markdown) and get grounded answers that cite the exact source files they came from. Questions an administrator has already verified are answered straight from a database of approved answers.

## Status

Phases 1-9 and 11 of the [implementation plan](docs/06_IMPLEMENTATION_PLAN.md) are done. Deployment (Phase 10) is written but not run.

| Measured on the fixed eval sets | Result |
|---|---|
| Right file in the top 5 search results (40 questions) | 67.5% (was 40% at the start) |
| "Where is X defined" questions answered with the defining file first | 100% |
| Local answers that cite a source / cite the right file | 100% / 85% |
| Off-topic questions correctly refused | 7 of 8 |
| Verified-answer false matches (40 paraphrase/near-miss pairs) | 0 |

Full tables are in [`docs/01_PRD.md`](docs/01_PRD.md).

## How it works

```
codebase ─┬─ full build / incremental sync ─→ AST-aware chunks ─→ bge-small embeddings (ChromaDB)
          │                                                   └→ BM25 + symbol-definition index (memory)
question ─→ rewrite follow-up ─→ approved answer in the verified database? ── yes ─→ stored answer + sources
                                          │ no
                                          └→ vector + BM25 + definitions → fused top-k → Qwen2.5-3B → answer checker → streamed, cited answer
```

## Run it locally

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                # set SENTINEL_API_KEY (the admin key), optionally ANTHROPIC_API_KEY
```

An NVIDIA GPU is recommended for the local model: `pip install --force-reinstall --no-deps torch==2.12.0+cu130 --index-url https://download.pytorch.org/whl/cu130`.

Put the corpus (a git clone of Superset) at `workspace/superset`, then build the index once (about 20 minutes on a laptop GPU):

```bash
python -m ingestion.chunker
python -m ingestion.build_vectorstore
```

Start the API, then create a regular key for the frontend (the admin key stays server-side):

```bash
uvicorn backend.app.main:app --port 8000
curl -X POST -H "X-API-Key: <admin key>" -H "Content-Type: application/json" -d '{"label":"frontend"}' http://127.0.0.1:8000/admin/keys
```

`frontend/.env.local`:

```
SENTINEL_API_URL=http://127.0.0.1:8000
SENTINEL_API_KEY=<the regular key from the previous step>
```

```bash
cd frontend && npm install && npm run dev
```

Open **http://localhost:3000** (use `localhost`: the Next.js dev server blocks its dev resources for `127.0.0.1`). The admin dashboard is at `/dashboard`; sign in with the admin key.

## Keeping the index current

```bash
curl -X POST -H "X-API-Key: <admin key>" "http://127.0.0.1:8000/admin/sync?pull=true"
```

This pulls the corpus, re-indexes only the files that changed, removes deleted ones, and marks affected verified answers stale. A run with no changes takes about 5 s; schedule it daily. With the API stopped you can run `python -m backend.app.sync --pull` instead.

## API

All routes except `/health` need an `X-API-Key` header; `/admin/*` needs the admin key.

| Route | Purpose |
|---|---|
| `POST /query`, `POST /query/stream` | Cited answer (SSE for the stream), served from a verified answer when one matches. Optional `session_id`, `top_k`, `language`, `path_prefix`, `mode` |
| `POST /search` | Retrieval only |
| `POST /sessions`, `GET /sessions`, `GET /sessions/{id}` | Conversations |
| `POST /messages/{id}/feedback` | Helpful (`1`) or not (`-1`) |
| `POST /documents/upload`, `GET /jobs/{id}`, `GET /documents?source=upload\|corpus`, `DELETE /documents/{id}` | Uploads and the file manifest |
| `GET /admin/dashboard`, `GET /admin/session` | Dashboard data, admin-key check |
| `GET /admin/verified`, `POST /admin/verified/drafts`, `POST /admin/verified/from-message/{id}`, `POST /admin/verified/{id}/approve`, `POST /admin/verified/{id}/reject`, `DELETE /admin/verified/{id}`, `GET /admin/verified/seeds` | Verified-answer review |
| `POST /admin/sync`, `GET /admin/sync` | Incremental sync and its history |
| `POST/GET/DELETE /admin/keys`, `GET /admin/stats` | API keys, usage stats |

## Evaluation and tests

```bash
python -m eval.run_eval                  # retrieval: hit@1/5/10, MRR, misses
python -m eval.run_answer_eval --prompt v2   # answer behaviour of the local model
python -m eval.run_matching_eval         # verified-answer threshold check
pip install -r requirements-dev.txt
python -m pytest tests -q && ruff check backend ingestion eval tests
```

## Licence note

The default local model, Qwen2.5-3B-Instruct, is under the Qwen Research licence: **non-commercial use only**. For commercial use, set `SENTINEL_LOCAL_LLM_MODEL` to an Apache-2.0 model (Qwen2.5-7B-Instruct with `SENTINEL_LOCAL_LLM_QUANT=4bit` scored the same) or set `ANTHROPIC_API_KEY`.

## Docs

The six planning documents in [`docs/`](docs/) (product, technical, app flow, UI/UX, schema, implementation plan) are the project's hard rules; [`docs/CONTEXT.md`](docs/CONTEXT.md) holds the engineering rules and decision log.
