# Product Requirements Document (PRD)

**Project:** Sentinel
**Status:** Living document — the source of truth for what "done" means; check new work against this before building it
**Related:** [`02_TRD.md`](02_TRD.md) · [`04_UI_UX_DESIGN_BRIEF.md`](04_UI_UX_DESIGN_BRIEF.md) · [`06_IMPLEMENTATION_PLAN.md`](06_IMPLEMENTATION_PLAN.md)

## 1. Problem statement

Engineers working in a large, mixed-language codebase lose real time answering questions like "how does this module work," "where is the code that does X," or "why was this built this way." Today that means grepping blind, interrupting a teammate who may not remember either, or asking a generic LLM chatbot that will answer confidently whether or not it actually knows — and a wrong answer delivered with full confidence about how code behaves is worse than no answer, because it leads directly to bugs built on a false premise.

## 2. Target users

**Primary — Onboarding Engineer.** Joined the team in the last 0-3 months. Owns or is about to own a piece of the codebase they haven't fully read yet. Needs fast, grounded orientation without burning a senior teammate's time on every question.

**Secondary — Cross-cutting Engineer.** Experienced on the team, but working a change that touches modules outside their usual area. Needs a fast way to understand an unfamiliar code path without a full read-through first.

**Explicitly not a target user (out of scope for v1):** end customers or non-engineers asking product questions. This is an internal engineering tool, not a customer support bot.

## 3. Goals

- Answer a natural-language question about a large codebase with a grounded, cited response, backed by real retrieved source excerpts — never an ungrounded guess.
- Generalize beyond the current Apache Superset corpus to any internal codebase or document set (already a hard architectural rule in `docs/CONTEXT.md`; this PRD makes it a product requirement, not just an engineering preference).
- Keep the index reasonably current as source files change, without requiring a human to remember to manually rebuild it.

## 4. Non-goals

- Not a general-purpose chatbot for questions unrelated to the indexed corpus.
- Not a code-generation or autocomplete tool.
- Not a multi-tenant SaaS product in this version — one organization's codebase per deployment.

## 5. Success metrics

These are measured against a real eval set (`eval/qa_set.json`, 40 questions with expected source files), not asserted. Run it with `python -m eval.run_eval`.

Retrieval results, measured 2026-10-18 on the Superset checkout (88,144 chunks). One question is 2.5 points, so differences of one question are within noise.

| Setup | hit@1 | hit@5 | hit@10 | MRR |
|---|---|---|---|---|
| Baseline: 80-line windows, MiniLM, vector | 17.5% | 40.0% | 50.0% | 0.267 |
| AST chunks, MiniLM, vector | 27.5% | 50.0% | 57.5% | 0.347 |
| AST chunks, MiniLM, hybrid | 30.0% | 65.0% | 65.0% | 0.434 |
| + test-file demotion | 37.5% | 67.5% | 67.5% | 0.486 |
| AST chunks, bge-small, vector | 37.5% | **70.0%** | 77.5% | 0.492 |
| **AST chunks, bge-small, hybrid (default)** | 37.5% | 67.5% | 77.5% | **0.506** |

Tried and rejected: the generic MS MARCO cross-encoder (lowered or did not change hit@5 in every comparison), a BGE query prefix (vector hit@5 70% to 60%), and 400-token chunks (hybrid MRR 0.453).

Where it still fails: 13 of 40 questions miss the top 5, mostly broad "how does X work" code questions where related files (for example the MCP service layer or API schemas) outrank the implementing file.

Targets below are provisional until there is more than one measurement per metric.

- **Retrieval hit-rate (hit@5):** % of a fixed 30-40 question eval set where the correct source file appears in the top-5 retrieved chunks. Provisional target: ≥ 70%. **Current: 67.5% (default hybrid), 70.0% with plain vector search. Baseline was 40%.**
- **Groundedness:** % of answer sentences that are actually supported by their cited source — checked manually against the eval set until an automated grounding check exists. Provisional target: ≥ 90%. **Not measured yet.**
- **p95 end-to-end latency** for `/query`. Provisional target: under 10 seconds on the API-based LLM path. The local-model path is exempt (see `02_TRD.md` section 4). **Current: one logged query on the local model with a GPU took 3.4 s end to end; the Anthropic path has not been measured because no API key was available.**
- **Uncited factual claims:** target is zero. The prompt asks for `[S1]`-style citations on every claim, but a 1.5B local model does not reliably comply, so this is requested, not enforced, and has not been measured. In manual checks the local model often skipped citations and once listed irrelevant files.

## 6. Must-have vs. nice-to-have

**Must-have (blocks calling this v1-complete):**
- `/query` returns a correct, cited answer over HTTP — **done**, fixed and verified live.
- Retrieval doesn't reload the embedding model per call — **done**.
- Incremental ingestion: a changed or new file updates the index without duplicating existing entries — **done** for uploads and for re-running the bulk build (stable path-derived ids, content hashing for uploads, old chunks deleted before re-indexing).
- An eval set exists and has been run at least once, producing a real number — **done**, see the results table in section 5.
- Basic auth on anything reachable outside localhost — **done**: `X-API-Key` on every route except `/health`, keys stored hashed.

**Should-have:**
- Hybrid retrieval, vector + BM25 — **done** (Phase 3).
- AST-aware chunking for Python — **done** (Phase 2).
- Streaming responses — **done** (Phase 5).

**Could-have:**
- Multi-turn conversation memory — **done** (Phase 6).
- Drag-and-drop file upload UI — **done** (Phase 8).
- A small PyTorch classifier routing "code" vs. "docs" queries — explicitly the lowest-priority, do-last item; a legitimate PyTorch rep but not load-bearing for the product.

## 7. Key user stories

- As an onboarding engineer, I ask "how does the chart caching layer work" and get an answer that cites the actual files it came from, not a plausible-sounding guess.
- As an engineer, when I re-run ingestion after a code change, the index reflects the change without doubling every existing chunk.
- As someone evaluating this project (an interviewer, a reviewer), I open the deployed link and get a working, cited answer on the first try — every time, not "usually."

## 8. Risks

- Local LLM answer quality may still miss the groundedness bar even once an eval set exists — this is the real motivation for the Phase 5 LLM swap, not a latency fix in disguise.
- Building hybrid search or better chunking before the eval set exists means neither improvement can actually be measured — a real sequencing risk, called out explicitly in the Implementation Plan.
