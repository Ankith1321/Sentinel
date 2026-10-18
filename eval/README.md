# eval/

Retrieval quality measurement for Sentinel.

- `qa_set.json`: 40 questions about the Superset codebase (20 code, 6 exact-identifier, 4 frontend, 10 docs). Each has the file(s) a good retriever must return and, for code, a `must_contain` marker that proves the file is the right one. Expected paths were chosen by reading the repo, not from retriever output.
- `run_eval.py`: scores a retrieval mode against the set and writes a timestamped JSON to `results/` (gitignored).

```bash
python -m eval.run_eval --validate                       # ground truth still matches the checkout?
python -m eval.run_eval --mode hybrid --label my_run     # hit@1, hit@5, hit@10, MRR, per type, plus every miss
```

Set `SENTINEL_COLLECTION` (and `SENTINEL_EMBEDDING_MODEL`) to score a different index. Re-run `--validate` after updating the Superset checkout, since files can move.
