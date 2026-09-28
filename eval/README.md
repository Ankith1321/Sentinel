# eval/

Not built yet. This is where the retrieval/answer-quality evaluation work lands (docs/SENIOR_REVIEW.md item 5, docs/CONTEXT.md Phase 9).

Planned:
- `qa_set.json` — a fixed set of real questions about the Superset codebase with expected sources/answers
- `run_eval.py` — scores retrieval hit-rate and answer groundedness against qa_set.json
