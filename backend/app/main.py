from fastapi import FastAPI
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from ingestion.retriever import retrieve    

from ingestion.rag_service import ask_sentinel


app = FastAPI(
    title="Sentinel API",
    description="RAG API for Apache Superset",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

@app.get("/")
def root():
    return {
        "service": "Sentinel API",
        "status": "running",
        "docs": "/docs",
        "health": "/health",
        "query": "/query",
    }

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

@app.post("/search")
def search(request: QueryRequest):
    results = retrieve(request.question, top_k=request.top_k)

    return {
        "question": request.question,
        "top_k": request.top_k,
        "results": [
            {
                "id": f"S{i}",
                "path": item["metadata"].get("path"),
                "language": item["metadata"].get("language"),
                "title": item["metadata"].get("title"),
                "distance": item.get("distance"),
                "preview": item["content"][:800],
            }
            for i, item in enumerate(results, start=1)
        ],
    }