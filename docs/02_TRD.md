# Technical Requirements

**Project:** Sentinel. **Status:** matches the code on 2026-11-21.

## Architecture

Two lifecycles share one vector store and one SQLite database.

- **Index time.** `python -m ingestion.chunker` then `python -m ingestion.build_vectorstore` scan, chunk, embed and upsert the corpus and record a per-file manifest (path, content hash, chunk count) in SQLite. `python -m backend.app.sync` then re-indexes only files whose hash changed: it upserts the new chunks first, then deletes the old ones the file no longer produces, so a search never sees a file missing.
- **Query time.** Refuse instruction-override questions, rewrite a follow-up into a standalone question, retrieve (vector + BM25 + symbol definitions, fused with RRF), redact secret-shaped text, trim to a token budget by whole chunks, generate, check the answer, stream it, log it.

One API process, no queue. Only one process may write to the index, so stop the API before running the sync.

## Decisions

| Layer | Choice | Why | Rejected |
|---|---|---|---|
| API | FastAPI | Async, Pydantic validation at the boundary, free OpenAPI docs | Flask, Django |
| Vector store | ChromaDB, local | No external service; holds 146,435 chunks | Qdrant or Pinecone, once it must scale past one machine |
| Relational store | SQLite | One file; sessions, messages, feedback, query log, file manifest | PostgreSQL, only with more than one API instance |
| Embeddings | `BAAI/bge-small-en-v1.5` (384 dims) | Vector hit@5 70% against 50% for MiniLM on the same chunks | bge-large (3x the storage, no eval number to justify it); a BGE query prefix (hit@5 70% to 60%) |
| Chunks | 200 tokens (max 240) of the embedder | 400-token chunks scored worse (MRR 0.453 against 0.506) | Fixed line windows (hit@5 40%) |
| Keyword search | `rank_bm25` in memory plus a symbol-definition map | BM25 finds exact identifiers vectors miss; the map sends "where is X defined" to the defining chunk (100% at rank 1) | A search server, until the index outgrows RAM |
| Fusion | Weighted RRF (vector 1, BM25 1, definitions 3), test files x0.6 | Needs no score calibration; each weight was set on the eval | A cross-encoder re-ranker: it never improved hit@5, so it was removed |
| LLM | Claude when `ANTHROPIC_API_KEY` is set; an OpenAI-compatible endpoint when configured; local `Qwen2.5-3B-Instruct` fp16 on an NVIDIA GPU; otherwise no model | The 3B with the strict prompt matched the 7B on the answer eval at half the time. Licence: non-commercial | Fine-tuning facts into a model; 4-bit 7B (same quality, twice as slow) |
| No model | List the closest passages with `[S#]` citations | A free CPU-only server cannot run a 3B model usefully | Loading a 3B model on CPU |
| Frontend | Next.js 16 + Tailwind; a route handler is the only thing the browser calls and adds the key server-side | Keeps the key out of the JavaScript bundle | A `NEXT_PUBLIC_` key |
| CI | GitHub Actions: Ruff, pytest, frontend lint, type-check and build, then both Docker images | | |

## Measured behaviour

Single-user numbers on an RTX 4060 Laptop (8 GB) with 146,435 chunks. These are not load tests.

- Retrieval: about 0.9 s per question once warm. Start-up about 70-85 s, most of it the embedder, the keyword index and the model. The first run of the keyword index over all chunks alone takes about 80 s.
- Local answer: about 12 s. GPU memory about 7.2 of 8.2 GB with the 3B and the embedder loaded; only one local generation runs at a time.
- Sync with no changes over 7,545 files: about 5 s. A full build of the corpus: about 20 minutes on this GPU.

## Security

- `.env` and `frontend/.env.local` are gitignored. CORS is an explicit origin list, GET and POST only.
- One key, `SENTINEL_API_KEY`, sent as `X-API-Key` and compared in constant time. Every route except `/health` requires it.
- Inputs are length- and range-limited by Pydantic.
- Questions that try to override the instructions are refused before any model call. Secret-shaped strings (private keys, AWS and API keys, `password = "..."`) are redacted from the passages, the source previews and the final answer. Streamed tokens are not redacted one by one; because the passages are already clean, only invented text could leak.

## Configuration

`SENTINEL_CHROMA_PATH` sets where the index lives (point it at a mounted volume in a container). With no index the API still starts: `/health` reports `index_ready: false`, search routes answer 503 and the stream sends an `error` event. The test suite points everything at empty temporary paths, so tests never touch the real index.

## Open risks

- The Claude and OpenAI-compatible providers have never run against a real API.
- The container images build in CI but have never been started.
- Groundedness is measured only lexically.
