# Product Requirements Document (PRD)

**Project:** Sentinel
**Status:** Living document, the source of truth for what "done" means. Check new work against this before building it. Last updated 2026-10-19.
**Related:** [`02_TRD.md`](02_TRD.md) · [`04_UI_UX_DESIGN_BRIEF.md`](04_UI_UX_DESIGN_BRIEF.md) · [`06_IMPLEMENTATION_PLAN.md`](06_IMPLEMENTATION_PLAN.md)

## 1. Problem statement

Engineers working in a large, mixed-language codebase lose real time answering questions like "how does this module work," "where is the code that does X," or "why was this built this way." Today that means grepping blind, interrupting a teammate who may not remember either, or asking a generic LLM chatbot that will answer confidently whether or not it actually knows. A wrong answer delivered with full confidence about how code behaves is worse than no answer, because it leads directly to bugs built on a false premise.

## 2. Target users

**Primary — Onboarding Engineer.** Joined the team in the last 0-3 months. Owns or is about to own a piece of the codebase they haven't fully read yet. Needs fast, grounded orientation without burning a senior teammate's time on every question.

**Secondary — Cross-cutting Engineer.** Experienced on the team, but working a change that touches modules outside their usual area. Needs a fast way to understand an unfamiliar code path without a full read-through first.

**Administrator.** The person who runs the deployment. Reviews and approves the answers served from the verified-answers database, watches quality and usage on the dashboard, and triggers index syncs. Only this role can see the dashboard.

**Explicitly not a target user (out of scope for v1):** end customers or non-engineers asking product questions. This is an internal engineering tool, not a customer support bot.

## 3. Goals

- Answer a natural-language question about a large codebase with a grounded, cited response, backed by real retrieved source excerpts, never an ungrounded guess.
- Answer questions an administrator has already verified straight from a database of approved answers, instantly and consistently, with the same citations, as long as the cited source files have not changed since approval.
- Generalize beyond the current Apache Superset corpus to any internal codebase or document set.
- Keep the index current as source files change, without a manual rebuild.

## 4. Non-goals

- Not a general-purpose chatbot for questions unrelated to the indexed corpus.
- Not a code-generation or autocomplete tool.
- Not a multi-tenant SaaS product in this version: one organization's codebase per deployment.
- No model trained to answer from memory. Facts always come from retrieved source or from a human-approved answer whose sources are still unchanged (owner decision, 2026-10-19).

## 5. Success metrics

All numbers are measured, not asserted. Retrieval uses `eval/qa_set.json` (40 questions with expected source files, `python -m eval.run_eval`). Answer behaviour uses the same 40 plus 8 off-topic questions (`python -m eval.run_answer_eval`). Verified-answer matching uses 40 paraphrase and near-miss pairs (`python -m eval.run_matching_eval`). One question is 2.5 points, so a difference of one question is noise.

### 5.1 Retrieval (current corpus: Superset at 4f49d24151, 2026-10-18, 146,435 chunks)

| Setup | hit@1 | hit@5 | hit@10 | MRR |
|---|---|---|---|---|
| Right after the October pull (5 months, 3,803 commits) | 32.5% | 60.0% | 67.5% | 0.418 |
| + archived per-release doc copies excluded | 40.0% | 62.5% | 67.5% | 0.490 |
| **+ symbol-definition index (current default)** | **47.5%** | **67.5%** | 72.5% | **0.559** |

History on the earlier, smaller corpus (88,144 chunks): the original line-window chunker with MiniLM scored hit@5 40% (MRR 0.267), AST chunks 50%, hybrid search 65%, and bge-small hybrid 67.5% (MRR 0.506). Tried and rejected: the MS MARCO cross-encoder, a BGE query prefix, and 400-token chunks.

### 5.2 Answers (local model, strict prompt)

| Model | Cites a source | Cites the right file* | Names something not in the sources | Refuses off-topic | Seconds per answer |
|---|---|---|---|---|---|
| **Qwen2.5-3B-Instruct, fp16 (current)** | **100%** | **85%** | 5% | **7 of 8** | ~8 |
| Qwen2.5-7B-Instruct, 4-bit | 97.5% | 85% | 2.5% | 7 of 8 | ~16.5 |
| Qwen2.5-1.5B-Instruct (original) | 5% | 0% | 10% | 4 of 8 | ~9 |

*Of the answers where retrieval had found the expected file.

### 5.3 Targets

- **Retrieval hit@5:** at least 70%. Current: 67.5%.
- **Groundedness:** at least 90% of answer sentences supported by their cited source. Not measured yet beyond the automatic citation and unsupported-name checks above.
- **p95 end-to-end latency for `/query`:** under 10 s on the API path; the local path is exempt. Local 3B answers take roughly 8-15 s; verified answers return in well under a second.
- **Uncited factual claims:** zero. The strict prompt plus the answer checker flag any answer without a valid `[S#]`, and flagged answers show a "check this against the sources" note.
- **Verified-answer matching:** zero false matches (100% precision). Current: threshold 0.91, precision 100%, recall 45% on the 40-pair set. A missed match costs nothing, since the question goes through normal search.

## 6. Must-have vs. nice-to-have

**Must-have (blocks calling this v1-complete):**
- `/query` returns a correct, cited answer over HTTP: **done**.
- Retrieval doesn't reload the embedding model per call: **done**.
- Incremental ingestion: a changed, new or deleted file updates the index without duplicates or leftovers: **done** (uploads, and the corpus sync).
- An eval set exists and has been run: **done** (three evals, section 5).
- Auth on everything except `/health`; the dashboard and admin routes for the admin only: **done**.

**Should-have:**
- Hybrid retrieval with a symbol-definition index: **done**.
- AST-aware chunking: **done**.
- Streaming responses: **done**.
- Verified-answers database with admin review: **done** (owner request 2026-10-19).
- Admin dashboard: **done**.

**Could-have:**
- Multi-turn conversation memory: **done**.
- Drag-and-drop upload UI: **done**.
- A small PyTorch classifier routing "code" vs. "docs" queries: lowest priority, not started.

## 7. Key user stories

- As an onboarding engineer, I ask "how does the chart caching layer work" and get an answer that cites the actual files it came from, not a plausible-sounding guess.
- As an engineer, I ask a question someone already asked and an admin approved, and I get that approved answer instantly, marked "Verified", with its sources.
- As an administrator, I review drafted answers, edit and approve the good ones, and see an approved answer drop out of service automatically when one of its source files changes.
- As an engineer, when the codebase changes, the next sync reflects it without doubling or orphaning chunks.
- As someone evaluating this project, I open the deployed link and get a working, cited answer on the first try.

## 8. Risks

- **Licence.** The project model, Qwen2.5-3B-Instruct, is under the Qwen Research licence: non-commercial use only. A commercial deployment must switch to an Apache-2.0 model (Qwen2.5-7B-Instruct scored the same) or the Claude path. Owner decision, 2026-10-19.
- **Retrieval ceiling.** 13 of 40 questions still miss the top 5, mostly broad "how does X work" questions where related layers (the MCP service, API schemas) outrank the implementing file. No model can answer from a passage it never received.
- **Matching recall.** The small embedding model separates topics better than it separates questions, so only 45% of genuine paraphrases are recognised as the same question. This is deliberate (no false matches), but it limits how often the database is used.
- **The Claude path is unverified.** It is implemented and tested against a fake client only, because no API key has been available.
