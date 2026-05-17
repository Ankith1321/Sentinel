from fastapi import FastAPI
from pydantic import BaseModel, Field

from ingestion.rag_service import ask_sentinel


app = FastAPI(
    title="Sentinel API",
    description="RAG API for Apache Superset",
    version="0.1.0",
)


from typing import Any

class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3)
    top_k: int = Field(default=5, ge=1, le=15)
    
class SourceItem(BaseModel):
    id: str
    path: str | None = None
    language: str | None = None
    title: str | None = None
    distance: float | None = None
    preview: str | None = None


class QueryResponse(BaseModel):
    question: str
    answer: str
    sources: list[SourceItem]
    top_k: int
    model: str


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "sentinel-api",
    }


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest):
    result = ask_sentinel(
        question=request.question,
        top_k=request.top_k,
    )

    return result