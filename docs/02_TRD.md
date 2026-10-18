# Technical Requirements Document (TRD)

**Project:** Sentinel
**Status:** Living document — update when a stack or infra decision changes
**Related:** [`01_PRD.md`](01_PRD.md) · [`CONTEXT.md`](CONTEXT.md) · [`05_BACKEND_SCHEMA.md`](05_BACKEND_SCHEMA.md)

## 1. Overview

Sentinel is a retrieval-augmented generation service: a FastAPI backend that chunks and embeds a source codebase into ChromaDB, retrieves the most relevant chunks for a natural-language question, and generates a cited answer from an LLM. A Next.js frontend is the reference client. This document records *why* each technical choice was made, not just what it is — the decision log below is what future changes should be checked against before being reverted or second-guessed.

## 2. Architecture

Two independent lifecycles sharing one vector store:

- **Build time** (offline, currently manual): file scan → load → chunk → embed → upsert into ChromaDB.
- **Query time** (online, per request): embed question → vector search → retrieve top-k → prompt assembly → LLM generation → API response.

Both halves currently run as a single Python process each (a CLI script for build time, a FastAPI app for query time). There is no message queue, no background worker, and no load balancer — this is a single-instance service today, by design, not by oversight.

## 3. Stack decisions

| Layer | Choice | Why | Rejected |
|---|---|---|---|
| API framework | FastAPI | Native async, Pydantic validation at the boundary, auto-generated OpenAPI docs for free | Flask (no native async without extra tooling), Django (too heavy for a single-service API with no admin/ORM need) |
| Vector store | ChromaDB, persistent local client | Zero external infra, adequate up to roughly hundreds of thousands of vectors, fast to iterate on | Pinecone/Qdrant — real options once this needs to scale past a single machine or serve multiple instances; premature today, migration path deliberately left open in the decision log |
| Embedding model | `sentence-transformers/all-MiniLM-L6-v2`, 384-dim | Fast enough for CPU-only inference, no per-call API cost, adequate baseline quality | `BAAI/bge-large-en-v1.5` (1024-dim) — better quality but 3x the storage and slower on CPU; upgrade is gated on having an eval number to justify it (see PRD success metrics), not swapped on vibes |
| LLM (generation) | Local `Qwen/Qwen2.5-1.5B-Instruct` today; API-based (Claude Haiku / GPT-4o-mini) planned as the primary path | API models give materially better grounded-answer quality per dollar than a small local model run unoptimized | 7B+ local models without quantization — not viable on CPU-only dev hardware; fine-tuning a model on the codebase — goes stale the moment code changes and can't cite a source file |
| Frontend | Next.js 15 (App Router) + Tailwind | TypeScript, fast iteration, room to add API routes later if a BFF layer is ever needed | Plain React SPA (no server-rendering story), SvelteKit (smaller ecosystem fit for this stack) |
| Containerization | Docker — `docker/backend.Dockerfile`, `docker/docker-compose.yml` | Standard, portable, matches the eventual Azure deployment target | — |
| Deploy targets | GitHub (source), Hugging Face Spaces (public demo, port 7860 convention), Azure Container Apps (production target) | HF Spaces and Azure are not competing choices — HF is the free, fast public demo link; Azure is the actual "built for enterprise" story, and the roles this project targets named Azure specifically | Self-managed VM / bare Kubernetes as a first step — explicitly deferred per the roadmap until the core product works |

## 4. Non-functional requirements

- **Latency — retrieval:** ~35-40ms per call once the embedding model singleton is warm. Measured during Phase 1 verification on the CPU-only dev machine (two back-to-back `retrieve()` calls against a live Chroma collection). Re-measure after Phase 2/3, since chunk count and re-ranking will change it.
- **Latency — generation:** roughly 50-60 seconds observed during Phase 1 verification for a single ~220-token answer from the local Qwen 1.5B model on the CPU-only dev machine (no CUDA). This is not acceptable for an interactive product and is the direct, measured justification for Phase 5 (API-based LLM as the default path) — not a hypothetical concern.
- **Throughput:** not a current design target. This is a single-user local/demo deployment; no concurrency or load testing has been done.
- **Availability:** no uptime target exists yet. Revisit once an Azure deployment is live and has real traffic.
- **Data freshness:** currently none — the index only reflects whatever was on disk the last time someone manually ran the two ingestion scripts. See [`06_IMPLEMENTATION_PLAN.md`](06_IMPLEMENTATION_PLAN.md) Phase 4.

## 5. Security requirements

- Secrets never committed: `.env` is gitignored (verified).
- CORS: explicit origin allowlist, never a wildcard (verified in `backend/app/main.py`).
- Auth: none implemented yet. Required before any deployment reachable outside a private demo — tracked as Phase 7, not optional.
- Input validation: Pydantic field constraints (`min_length`, `ge`/`le`) already enforced on `QueryRequest`.

## 6. Constraints

- **CPU-only dev hardware, no CUDA.** Every model-loading change must be verified to actually run here before being called done — the Phase 1 `dtype=torch.float16` change was checked against a real matmul test and a real generation run specifically because float16 has a history of missing CPU kernels on older PyTorch builds. Don't assume a GPU-oriented fix "just works" on CPU; test it.
- **ChromaDB has no built-in horizontal scaling.** Fine up to roughly hundreds of thousands of chunks; the decision log already anticipates migrating past that point rather than treating it as a surprise.

## 7. Open technical risks

- No incremental ingestion — re-running the pipeline duplicates every chunk under new IDs (the `loader.py` fresh-UUID bug).
- Local LLM generation latency (50-60s/answer) is not viable for any interactive use case, only for offline batch eval.
- No authentication on a service intended to eventually be reachable outside localhost.
