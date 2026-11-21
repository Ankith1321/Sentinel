# Product Requirements

**Project:** Sentinel. **Status:** matches the code on 2026-11-21. The larger version with a dashboard, verified answers and uploads is in the git tag `full-version`.

## Problem

Engineers in a large, mixed-language codebase lose time on questions like "how does this module work" and "where is X defined". They grep blind, interrupt a teammate, or ask a generic chatbot that answers confidently whether or not it knows. A confident wrong answer about how code behaves is worse than none.

## Users

An engineer new to a codebase, or working outside their usual area, who wants a fast, checkable answer. Not in scope: non-engineers, customer support, code generation.

## Goals

- Answer a natural-language question with a response that cites the retrieved source files, and never answer from outside knowledge.
- Say so when no model is available, and still return the closest passages.
- Work for any corpus, not just Superset.
- Keep the index current without a full rebuild.

Non-goals: multi-tenant use, user accounts, fine-tuning a model on the code (it goes stale and cannot cite).

## Measured results

All numbers come from `eval/`. One question is 2.5 points, so a one-question difference is noise.

### Retrieval (Superset at 4f49d24151, 146,435 chunks, 40 questions)

| Setup | hit@1 | hit@5 | hit@10 | MRR |
|---|---|---|---|---|
| Right after pulling 5 months of commits | 32.5% | 60.0% | 67.5% | 0.418 |
| + archived per-release doc copies excluded | 40.0% | 62.5% | 67.5% | 0.490 |
| **+ symbol-definition index (current)** | **47.5%** | **67.5%** | 72.5% | **0.559** |

On the earlier, smaller corpus (88,144 chunks): the first line-window chunker with MiniLM scored hit@5 40% (MRR 0.267), AST chunks 50%, hybrid search 65%, bge-small hybrid 67.5% (MRR 0.506).

### Answers (Qwen2.5-3B-Instruct, fp16, strict prompt, 2026-11-21)

| Measure | Result |
|---|---|
| Cites a source | 100% |
| Cites the right file, when retrieval found it | 81.5% (22 of 27) |
| Names something not in the sources | 2.5% |
| Refuses off-topic questions | 7 of 8 |
| Seconds per answer | about 11.6 |
| Answer sentences with at least half their content words in the passages | 76.2% of 126 |

The last row is a lexical floor, not a groundedness verdict: a paraphrase counts as unsupported. The earlier 1.5B model cited a source in 5% of answers.

### Guardrails

16 prompt-injection attempts are refused and 16 look-alike codebase questions are answered normally (`tests/test_guardrails.py`).

## Status of the requirements

| Requirement | State |
|---|---|
| Cited answers over HTTP, streamed | Done |
| Hybrid retrieval with a symbol-definition index | Done |
| AST-aware chunking | Done |
| Incremental sync by content hash | Done (`python -m backend.app.sync`) |
| Sessions and follow-up rewriting | Done |
| One API key on every route but `/health` | Done |
| Guardrails: injection refusal, secret redaction | Done |
| Retrieval-only answers with no model | Done |
| Evaluation suite | Done |
| Hand-reviewed groundedness of about 30 answers | Not done |
| Deployment | Not done |

## Risks

- **Licence.** Qwen2.5-3B-Instruct is non-commercial. A commercial deployment must use an Apache-2.0 model or the Claude path.
- **Retrieval ceiling.** 13 of 40 questions miss the top 5, mostly broad "how does X work" questions. A model cannot answer from a passage it never received.
- **Unverified model paths.** The Claude and OpenAI-compatible providers have never run against a real API.
