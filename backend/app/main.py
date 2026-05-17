from fastapi import FastAPI
from pydantic import BaseModel, Field

from ingestion.rag_engine import generate_answer


app = FastAPI(
    title="Sentinel API",
    description="RAG API for Apache Superset",
    version="0.1.0",
)


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3)
    top_k: int = Field(default=5, ge=1, le=15)


class QueryResponse(BaseModel):
    question: str
    answer: str


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "sentinel-api",
    }


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest):
    answer = generate_answer(
        question=request.question,
        top_k=request.top_k,
    )

    return QueryResponse(
        question=request.question,
        answer=answer,
    )