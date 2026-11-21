#!/usr/bin/env bash
# Publish the current commit to the Hugging Face Space as a normal (fast-forward) commit.
# Needs: the `hf` git remote, and a Hugging Face login with write access to the Space.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

source_commit="$(git rev-parse --short HEAD)"
git fetch hf main

work="$(mktemp -d)"
git worktree add --detach "$work" hf/main

git -C "$work" rm -r -q --ignore-unmatch .
git archive HEAD requirements.txt backend ingestion frontend deploy/space | tar -x -C "$work"
cp deploy/space/Dockerfile "$work/Dockerfile"

cat > "$work/README.md" <<'SPACE_README'
---
title: Sentinel
colorFrom: gray
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

Sentinel answers questions about the Apache Superset codebase and cites the files it used.
This free Space has no GPU and no API key, so it lists the closest passages with their file paths
instead of writing an answer. Source and results: https://github.com/Ankith1321/Sentinel
SPACE_README

git -C "$work" add -A
git -C "$work" commit -q -m "Deploy ${source_commit}"
git -C "$work" push hf HEAD:main
git worktree remove --force "$work"
