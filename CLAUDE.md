# Sentinel

Knowledge assistant over the Apache Superset codebase. Backend: FastAPI + ChromaDB + SQLite + sentence-transformers (bge-small) + Claude, an OpenAI-compatible endpoint, local Qwen2.5-3B, or no model (closest passages). Frontend: Next.js 16 chat page with a server-side proxy.

Read before changing behaviour, and update in the same piece of work when a change departs from them:
- Goals, measured results, status: @docs/01_PRD.md
- Technical decisions, what was tried and rejected: @docs/02_TRD.md

Known state (2026-11-21): the project was reduced to a lean version. The dashboard, verified answers, uploads and key management are removed and kept in the git tag `full-version`. Not done: deployment, a hand review of groundedness, and a run of the Claude and OpenAI-compatible paths against a real API. Every quality claim must come from the eval suites in `eval/`.

## Engineering rules

- Paths come from `ingestion/config.py` or environment variables, never hardcoded. Models and DB clients are module-level singletons, never created in a request handler.
- Vector store writes use upsert. Compare the content hash before embedding. When a file is re-indexed, upsert the new chunks first, then delete the ones it no longer produces. Only one process writes to the index.
- Chunk size is measured in embedder tokens (200 target, 240 max). Python is cut at function and class boundaries; every chunk starts with its file path. Embeddings are normalized; fetch at least 20 candidates before cutting to `top_k`. Every retrieval change is measured on `eval/qa_set.json` before and after.
- The LLM answers only from the numbered passages and cites `[S1]`, `[S2]`; max new tokens are bounded; context is trimmed by whole chunks, never mid-chunk.
- Code: no comments that explain what the code does (only a non-obvious why), no unused imports, no dead code, imports at the top, `logging` not `print`, Pydantic models for every API shape, every route handler returns. `ruff check backend ingestion eval tests` and `pytest tests` pass before a commit.
- Security: `.env`, `frontend/.env.local`, `data/` and `eval/results/` are gitignored. No CORS wildcard. Every route except `/health` needs `X-API-Key`. Validate input lengths and ranges at the API boundary.
- Frontend: the browser calls only the `/api` proxy; the key stays server-side. Every error state is rendered. No `console.log`. Check with `npm run lint && npx tsc --noEmit && npm run build`.
- Git: work on `ankith`. Never force-push. Nothing is pushed, and `main` is not touched, without the owner's go-ahead. Conventional commit messages that say why, not what.

## Hard rule — no unsolicited .md files

Never create, write, or save a new `.md` file anywhere in this project unless the user has explicitly asked for that specific file in that turn. This applies to every kind of markdown file — reviews, plans, summaries, recaps, roadmaps, READMEs, notes — no exceptions for "helpful" or "durable" documentation. Doing analysis, a review, or a recap is fine; the output goes in the chat response, not into a new file, unless the user's message explicitly asks for a file/document to be written or saved. When in doubt, answer in chat and ask before creating a file.
