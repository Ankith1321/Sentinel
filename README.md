# Sentinel

An internal engineering knowledge assistant: ask natural-language questions over a large, mixed-language codebase (currently Apache Superset — Python, TypeScript, Markdown) and get grounded, cited answers instead of generic LLM guesses.

## Status

Actively being built, not production-ready yet. The ingestion → chunking → embedding → ChromaDB pipeline works end to end. The `/query` endpoint has a known bug and currently does not return a response — see `docs/CONTEXT.md` section 6 for the full list. `/search` (retrieval only, no LLM step) works.

## Stack

FastAPI · ChromaDB · sentence-transformers (`all-MiniLM-L6-v2`) · Qwen2.5-1.5B-Instruct locally, being replaced by an API-based model · Next.js 15 + Tailwind

## Layout

- `backend/` — FastAPI app and routes
- `ingestion/` — file scanning, chunking, embedding, retrieval, answer generation
- `frontend/` — Next.js chat UI
- `data/` — processed chunks + vector index, gitignored, generated locally
- `docker/` — Dockerfile and compose setup
- `docs/` — full architecture spec (`CONTEXT.md`) and the engineering roadmap (`SENIOR_REVIEW.md`)
- `eval/` — retrieval/answer quality evaluation, planned, not built yet

## Running locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m ingestion.chunker
python -m ingestion.build_vectorstore

uvicorn backend.app.main:app --reload --port 8000
```

Frontend, in a second terminal:

```bash
cd frontend
npm install
npm run dev
```

## Docs

- [`docs/CONTEXT.md`](docs/CONTEXT.md) — full architecture, mandatory engineering rules, current bugs, phase-by-phase roadmap
- [`docs/SENIOR_REVIEW.md`](docs/SENIOR_REVIEW.md) — prioritized plan for taking this from working prototype to a resume-ready project
