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

These need to be measured against a real eval set, not asserted. No eval set exists yet — building one is the single highest-priority item that isn't already done, because every quality claim elsewhere in this project (chunking is better, hybrid search improved retrieval, etc.) is currently unfalsifiable without it.

- **Retrieval hit-rate:** % of a fixed 30-40 question eval set where the correct source file appears in the top-k retrieved chunks.
- **Groundedness:** % of answer sentences that are actually supported by their cited source — checked manually against the eval set until an automated grounding check exists.
- **p95 end-to-end latency** for `/query`.
- **Zero uncited factual claims** in the answer — already enforced by the prompt's instructions, not yet independently measured.

## 6. Must-have vs. nice-to-have

**Must-have (blocks calling this v1-complete):**
- `/query` returns a correct, cited answer over HTTP — **done**, fixed and verified live.
- Retrieval doesn't reload the embedding model per call — **done**.
- Incremental ingestion: a changed or new file updates the index without duplicating existing entries — **not done** (Implementation Plan Phase 4).
- An eval set exists and has been run at least once, producing a real number — **not done** (Phase 9, but see the sequencing note in the Implementation Plan — this needs to move earlier).
- Basic auth on anything reachable outside localhost — **not done** (Phase 7).

**Should-have:**
- Hybrid retrieval, vector + BM25 (Phase 3).
- AST-aware chunking for Python (Phase 2).
- Streaming responses (Phase 5).

**Could-have:**
- Multi-turn conversation memory (Phase 6).
- Drag-and-drop file upload UI (Phase 8).
- A small PyTorch classifier routing "code" vs. "docs" queries — explicitly the lowest-priority, do-last item; a legitimate PyTorch rep but not load-bearing for the product.

## 7. Key user stories

- As an onboarding engineer, I ask "how does the chart caching layer work" and get an answer that cites the actual files it came from, not a plausible-sounding guess.
- As an engineer, when I re-run ingestion after a code change, the index reflects the change without doubling every existing chunk.
- As someone evaluating this project (an interviewer, a reviewer), I open the deployed link and get a working, cited answer on the first try — every time, not "usually."

## 8. Risks

- Local LLM answer quality may still miss the groundedness bar even once an eval set exists — this is the real motivation for the Phase 5 LLM swap, not a latency fix in disguise.
- Building hybrid search or better chunking before the eval set exists means neither improvement can actually be measured — a real sequencing risk, called out explicitly in the Implementation Plan.
