FROM python:3.10-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/app/.cache/huggingface

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch==2.12.0 --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

COPY ingestion ./ingestion
COPY backend ./backend

RUN python -c "from sentence_transformers import CrossEncoder, SentenceTransformer; from ingestion.config import EMBEDDING_MODEL, RERANK_MODEL; SentenceTransformer(EMBEDDING_MODEL); CrossEncoder(RERANK_MODEL)"

RUN useradd --create-home sentinel && mkdir -p /app/data && chown -R sentinel /app
USER sentinel

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/health')"

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "7860"]
