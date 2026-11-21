FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/app/.cache/huggingface \
    SENTINEL_INDEX_REPO=Ankith13/sentinel-index

WORKDIR /app

COPY --from=web /usr/local/bin/node /usr/local/bin/node

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch==2.12.0 --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

COPY ingestion ./ingestion
COPY backend ./backend

RUN python -c "from sentence_transformers import SentenceTransformer; from ingestion.config import EMBEDDING_MODEL; SentenceTransformer(EMBEDDING_MODEL)"

COPY --from=web /web/.next/standalone ./web
COPY --from=web /web/.next/static ./web/.next/static
COPY --from=web /web/public ./web/public
COPY deploy/space/start.sh ./start.sh

RUN useradd -m -u 1000 user && mkdir -p /app/data && chown -R 1000:1000 /app
USER user

EXPOSE 7860

CMD ["bash", "start.sh"]
