# eval/

Measurement for Sentinel. Every quality claim in the docs comes from one of these. Results are written to `results/` (gitignored) and shown on the admin dashboard.

| File | What it measures | Run |
|---|---|---|
| `qa_set.json` + `run_eval.py` | Retrieval: 40 questions (20 code, 6 identifier, 4 frontend, 10 docs) with the file(s) that must come back; reports hit@1/5/10, MRR and every miss. Code questions carry a `must_contain` marker, checked by `--validate`, so the answer key does not depend on the retriever. | `python -m eval.run_eval` (`--validate`, `--mode`, `--label`) |
| `unanswerable.json` + `run_answer_eval.py` | Answer behaviour of the local model: does it cite, cite the right file, name things not in the sources, and refuse the 8 off-topic questions. | `python -m eval.run_answer_eval --prompt v2` |
| `verified_matching.json` + `run_matching_eval.py` | The verified-answer threshold: 20 paraphrases that should match and 20 near-misses that must not. Reports matches, false matches and recall per threshold. | `python -m eval.run_matching_eval` |
| `verified_seed_questions.json` | 60 starter questions an onboarding engineer would ask. The dashboard drafts answers for them into the review queue; they are not a test set. | via the dashboard |

Set `SENTINEL_COLLECTION`, `SENTINEL_EMBEDDING_MODEL` or `SENTINEL_LOCAL_LLM_MODEL` to measure another index or model. Re-run `python -m eval.run_eval --validate` after updating the corpus, since files can move.
