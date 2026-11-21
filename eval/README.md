# eval/

Measurement for Sentinel. Every quality claim in the docs comes from one of these. Results are written to `results/` (gitignored).

| File | What it measures | Run |
|---|---|---|
| `qa_set.json` + `run_eval.py` | Retrieval: 40 questions (20 code, 6 identifier, 4 frontend, 10 docs) with the file(s) that must come back; reports hit@1/5/10, MRR and every miss. Code questions carry a `must_contain` marker, checked by `--validate`, so the answer key does not depend on the retriever. | `python -m eval.run_eval` (`--validate`, `--mode`, `--label`) |
| `unanswerable.json` + `run_answer_eval.py` | Answer behaviour of the local model: does it cite, cite the right file, name things not in the sources, refuse the 8 off-topic questions, and how many answer sentences are supported by the passages (lexical check). | `python -m eval.run_answer_eval --prompt v2` |
| `guardrail_cases.json` | 16 prompt-injection attempts and 16 look-alike codebase questions; checked by `tests/test_guardrails.py`. | `python -m pytest tests/test_guardrails.py` |

Set `SENTINEL_COLLECTION`, `SENTINEL_EMBEDDING_MODEL` or `SENTINEL_LOCAL_LLM_MODEL` to measure another index or model. Re-run `python -m eval.run_eval --validate` after updating the corpus, since files can move.
