# Sentinel

An internal engineering knowledge assistant: ask natural-language questions over a large, mixed-language codebase (currently Apache Superset: Python, TypeScript, Markdown) and get grounded answers that cite the exact source files they came from.

## Status

End to end and tested: chunk → embed → hybrid retrieval → LLM answer with citations → streaming API → chat UI, with sessions, uploads, feedback and API-key auth. Retrieval quality is measured on a fixed 40-question eval set (see [Evaluation](#evaluation)): the top-5 results contain the right file 67.5% of the time, up from 40% before the chunking and hybrid-search work (full table in `docs/01_PRD.md`).

## How it works

```
files → AST-aware chunks → embeddings (ChromaDB) ─┐
                         └→ BM25 keyword index  ──┤→ Reciprocal Rank Fusion → top-k chunks → LLM → cited answer
```

- **Chunking:** Python is split at function and class boundaries with `ast`; TypeScript/JavaScript at top-level declarations; Markdown at headings. Chunks are measured in tokens of the embedding model and each starts with its file path.
- **Retrieval:** vector search and BM25 are fused with Reciprocal Rank Fusion. Modes: `vector`, `keyword`, `hybrid`, `hybrid_rerank` (set with `SENTINEL_RETRIEVAL_MODE`).
- **Generation:** Claude via the Anthropic API when `ANTHROPIC_API_KEY` is set, otherwise a local Qwen model. Answers may only use the retrieved passages and must cite them as `[S1]`, `[S2]`.

## Layout

- `backend/app/` FastAPI app, auth, SQLite store, upload handling
- `ingestion/` scanning, chunking, embedding, retrieval, LLM providers, answer assembly
- `frontend/` Next.js chat and documents UI, with a server-side proxy that keeps the API key off the browser
- `eval/` the 40-question eval set and its runner
- `tests/` unit and API tests
- `docker/` backend Dockerfile and compose file (the frontend Dockerfile is in `frontend/`)
- `docs/` the six planning documents, plus `sentinel-blueprint.html`, an interactive one-page version of them

## Run it locally

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                # then set SENTINEL_API_KEY (and ANTHROPIC_API_KEY if you have one)
```

NVIDIA GPU (optional, makes embedding and the local model much faster): install a CUDA build of PyTorch, for example
`pip install --force-reinstall --no-deps torch==2.12.0+cu130 --index-url https://download.pytorch.org/whl/cu130`.

Put the Superset checkout at `workspace/superset`, then build the index:

```bash
python -m ingestion.chunker
python -m ingestion.build_vectorstore
```

Start the API and the UI:

```bash
uvicorn backend.app.main:app --port 8000

cd frontend
cp .env.example .env.local        # or create it with SENTINEL_API_URL and SENTINEL_API_KEY
npm install && npm run dev
```

`frontend/.env.local`:

```
SENTINEL_API_URL=http://127.0.0.1:8000
SENTINEL_API_KEY=<same value as in the root .env>
```

Docker: `docker compose -f docker/docker-compose.yml up --build` (needs the index in `data/`).

## API

All routes except `/health` need an `X-API-Key` header.

| Route | Purpose |
|---|---|
| `POST /query` | Cited answer. Optional `session_id` for multi-turn, plus `top_k`, `language`, `path_prefix`, `mode` |
| `POST /query/stream` | Same, streamed as server-sent events: `sources`, `token`, `done`, `error` |
| `POST /search` | Retrieval only, no LLM |
| `POST /sessions`, `GET /sessions`, `GET /sessions/{id}` | Conversations and their history |
| `POST /messages/{id}/feedback` | Thumbs up (`1`) or down (`-1`) on an answer |
| `POST /documents/upload` | Upload `.py .md .mdx .js .ts .tsx .txt .pdf .docx`. Returns a job id at once; processing runs in the background |
| `GET /jobs/{id}`, `GET /documents`, `DELETE /documents/{id}` | Job status, indexed documents, removal |
| `POST/GET/DELETE /admin/keys` | Create, list, revoke API keys (admin key only) |

## Evaluation

```bash
python -m eval.run_eval --validate                      # check the ground truth against the repo
python -m eval.run_eval --mode hybrid --label my_run    # score retrieval; results go to eval/results/
```

It reports hit@1, hit@5, hit@10 and MRR overall and per question type, and lists every miss.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
ruff check backend ingestion eval tests
```

## Docs

- [`docs/01_PRD.md`](docs/01_PRD.md), [`02_TRD.md`](docs/02_TRD.md), [`03_APP_FLOW.md`](docs/03_APP_FLOW.md), [`04_UI_UX_DESIGN_BRIEF.md`](docs/04_UI_UX_DESIGN_BRIEF.md), [`05_BACKEND_SCHEMA.md`](docs/05_BACKEND_SCHEMA.md), [`06_IMPLEMENTATION_PLAN.md`](docs/06_IMPLEMENTATION_PLAN.md)
- [`docs/CONTEXT.md`](docs/CONTEXT.md): architecture and the mandatory engineering rules
