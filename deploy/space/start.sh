#!/usr/bin/env bash
set -euo pipefail

# The browser never sees this key: only the Next.js server and the API inside this container use it.
export SENTINEL_API_KEY="${SENTINEL_API_KEY:-$(python -c 'import secrets; print(secrets.token_urlsafe(32))')}"
export SENTINEL_CHROMA_PATH="${SENTINEL_CHROMA_PATH:-/app/data/indexes/chroma}"

python -m ingestion.fetch_index

python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 &

cd web
export SENTINEL_API_URL=http://127.0.0.1:8000 PORT=7860 HOSTNAME=0.0.0.0
exec node server.js
