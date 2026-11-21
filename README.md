# Sentinel

A knowledge assistant for large codebases. Ask a question in plain English about Apache Superset (Python, TypeScript, Markdown) and get an answer that cites the exact files it came from, or, if no language model is available, the closest passages with their file paths.

The point of the project is the retrieval and the measurement behind it: every number below comes from a fixed eval set in [`eval/`](eval/), run on the real index (146,435 chunks from 7,545 files).

## Results

| Measured | Result |
|---|---|
| Right file in the top 5 results (40 questions) | **67.5%**, up from 40% with the first line-window chunker |
| "Where is X defined" questions with the defining file first | 100% (6 questions) |
| Local answers (Qwen2.5-3B) that cite a source / the right file | 100% / 81.5% (22 of 27) |
| Off-topic questions refused | 7 of 8 |
| Answer sentences with at least half their content words in the passages | 76.2% of 126, a lexical floor and not a verdict (paraphrases count as unsupported) |
| Prompt-injection cases classified correctly (16 attacks, 16 look-alikes) | 32 of 32 |
| Latency on a laptop GPU | retrieval about 0.9 s, local answer about 12 s |

How retrieval got from 40% to 67.5%: AST-aware chunks (50%), hybrid vector + BM25 search (65%), a better embedder and a symbol-definition index (67.5%, measured on a corpus that grew from 88k to 146k chunks along the way). Tried and rejected, because the eval said no: a cross-encoder re-ranker (no gain), a BGE query prefix (vector hit@5 70% to 60%), 400-token chunks (MRR 0.453 against 0.506), and a 4-bit 7B model (same quality as the 3B at twice the time).

## How it works

```
codebase ── chunker + build_vectorstore / sync ──> AST-aware chunks ──> bge-small embeddings (ChromaDB)
                                                                    └─> BM25 + symbol-definition index (memory)

question ──> guardrail (refuses "ignore your instructions") ──> rewrite follow-up
         ──> vector + BM25 + definitions, fused with RRF ──> top-k passages (secrets redacted)
         ──> LLM: Claude | OpenAI-compatible | local Qwen2.5-3B | none (list the passages)
         ──> answer checker ──> streamed answer with [S1] citations
```

| Part | What it does |
|---|---|
| `ingestion/chunker.py` | Splits Python at function and class boundaries with `ast`, TypeScript at top-level declarations, Markdown at headings; 200-token chunks that each start with their file path |
| `ingestion/retriever.py` | Vector, BM25 and a symbol-definition lookup, fused with weighted Reciprocal Rank Fusion; test files demoted |
| `ingestion/rag_service.py`, `llm.py` | Follow-up rewriting, context budget by whole chunks, strict citation prompt, provider choice |
| `ingestion/answer_checks.py`, `guardrails.py` | Flags answers with no valid citation or invented names; refuses injection attempts; redacts secret-shaped text |
| `backend/app/` | FastAPI, one API key, SQLite for sessions, feedback and the query log, streaming over SSE |
| `backend/app/sync.py` | Re-indexes only files whose content hash changed |
| `frontend/` | Next.js chat page with streaming, citations and a server-side proxy that keeps the key off the browser |

## Run it locally

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                # set SENTINEL_API_KEY to a long random value
```

An NVIDIA GPU is recommended for the local model: `pip install --force-reinstall --no-deps torch==2.12.0+cu130 --index-url https://download.pytorch.org/whl/cu130`. Without a GPU or an API key the app still works and answers with the closest passages.

Put the corpus (a git clone of Superset) at `workspace/superset`, then build the index once (about 20 minutes on a laptop GPU):

```bash
python -m ingestion.chunker
python -m ingestion.build_vectorstore
```

Start the API (it needs about 70 seconds to warm up):

```bash
uvicorn backend.app.main:app --port 8000
```

`frontend/.env.local` (server-side only; the key is the same `SENTINEL_API_KEY`):

```
SENTINEL_API_URL=http://127.0.0.1:8000
SENTINEL_API_KEY=<the value from .env>
```

```bash
cd frontend && npm install && npm run dev
```

Open **http://localhost:3000**. Use `localhost`: the Next.js dev server blocks its dev resources for `127.0.0.1`.

To pick up new commits in the corpus, stop the API and run `python -m backend.app.sync --pull`. A run with no changes takes about 5 seconds.

## API

Every route except `/health` needs an `X-API-Key` header.

| Route | Purpose |
|---|---|
| `POST /query`, `POST /query/stream` | Cited answer (SSE for the stream). Optional `session_id`, `top_k`, `language`, `path_prefix`, `mode` |
| `POST /search` | Retrieval only |
| `POST /sessions`, `GET /sessions`, `GET /sessions/{id}` | Conversations |
| `POST /messages/{id}/feedback` | Helpful (`1`) or not (`-1`) |
| `GET /health` | Status and whether an index is loaded |

## Evaluate and test

```bash
python -m eval.run_eval                      # retrieval: hit@1/5/10, MRR, misses
python -m eval.run_answer_eval --prompt v2   # citations, refusals, sentence support
pip install -r requirements-dev.txt
python -m pytest tests -q && ruff check backend ingestion eval tests
```

CI (`.github/workflows/ci.yml`) runs lint and tests, the frontend lint, type-check and build, and builds both Docker images.

## Deploy to a free Hugging Face Space

The Space runs one container (the Next.js UI on port 7860 and the API behind it) on the free CPU tier. With no GPU and no API key it uses the retrieval-only mode, so it costs nothing.

```bash
python -m ingestion.fetch_index --publish <your-user>/sentinel-index   # once; stop the API first; needs `hf auth login`
bash deploy/space/push.sh                                              # pushes the current commit to the `hf` remote
```

The container downloads the index from that dataset on start (set `SENTINEL_INDEX_REPO` in `deploy/space/Dockerfile` to your dataset). Expect a few minutes of warm-up on a cold start; a free Space sleeps after 48 hours idle and wakes on the next visit. The image is built in CI on every push, but it has not been started anywhere yet.

## Limits, stated plainly

- Retrieval misses 13 of 40 questions in the top 5, mostly broad "how does X work" questions where related layers outrank the implementing file.
- Groundedness is only measured lexically. A hand review of about 30 answers is the honest next step.
- The Claude path and the OpenAI-compatible path have never run against a real API: Claude is tested with a fake client, the other with a mock server.
- It is a single-user design: one API key, one process writing to the index.
- Not deployed yet. A free Hugging Face Space would run the retrieval-only mode, because it has no GPU and no API key.
- The default local model, Qwen2.5-3B-Instruct, is under the Qwen Research licence: **non-commercial use only**. For commercial use set `SENTINEL_LOCAL_LLM_MODEL` to an Apache-2.0 model or set `ANTHROPIC_API_KEY`.

A larger version with an admin dashboard, a verified-answers review queue and file uploads is kept in the git tag `full-version`.

## Docs

[`docs/01_PRD.md`](docs/01_PRD.md) holds the goals and the full results tables; [`docs/02_TRD.md`](docs/02_TRD.md) holds the technical decisions and what was tried and rejected.
