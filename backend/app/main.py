import json
import logging
import os
from collections.abc import Iterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from backend.app import store
from backend.app.auth import require_api_key
from backend.app.db import init_db
from ingestion.config import CORS_ORIGINS, LOG_LEVEL, RETRIEVAL_MODE
from ingestion.guardrails import BLOCKED_ANSWER, injection_reason
from ingestion.llm import get_provider
from ingestion.rag_service import ask_sentinel, stream_sentinel
from ingestion.retriever import IndexUnavailable, get_keyword_index, get_model, get_reranker, index_ready, retrieve

logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
for noisy in ("httpx", "httpcore", "huggingface_hub", "sentence_transformers", "urllib3", "filelock"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

Language = Literal["python", "markdown", "javascript", "typescript", "text"]
RetrievalMode = Literal["vector", "keyword", "hybrid", "hybrid_rerank"]
GUARDRAIL_MODEL_LABEL = "guardrail"
INDEX_UNAVAILABLE_DETAIL = "The search index is not available on this server."


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=15)
    session_id: str | None = Field(default=None, min_length=1, max_length=64)
    language: Language | None = None
    path_prefix: str | None = Field(default=None, min_length=1, max_length=200)
    mode: RetrievalMode | None = None


class SourceItem(BaseModel):
    id: str
    path: str | None = None
    language: str | None = None
    title: str | None = None
    distance: float | None = None
    score: float | None = None
    preview: str | None = None


class AnswerChecks(BaseModel):
    cited_sources: list[int]
    invalid_citations: list[int]
    unsupported_terms: list[str]
    abstained: bool
    needs_review: bool


class QueryResponse(BaseModel):
    question: str
    standalone_question: str
    answer: str
    sources: list[SourceItem]
    top_k: int
    model: str
    retrieval_ms: int
    generation_ms: int
    checks: AnswerChecks | None = None
    session_id: str | None = None
    message_id: int | None = None


class SearchResponse(BaseModel):
    question: str
    top_k: int
    results: list[SourceItem]


class HealthResponse(BaseModel):
    status: str
    service: str
    index_ready: bool


class RootResponse(BaseModel):
    service: str
    status: str
    docs: str
    health: str
    query: str


class SessionCreated(BaseModel):
    session_id: str


class SessionSummary(BaseModel):
    id: str
    created_at: str
    last_active_at: str
    first_question: str | None = None


class MessageItem(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    content: str
    sources: list[SourceItem] | None = None
    created_at: str


class SessionDetail(BaseModel):
    id: str
    created_at: str
    last_active_at: str
    messages: list[MessageItem]


class FeedbackRequest(BaseModel):
    rating: Literal[-1, 1]


class FeedbackResponse(BaseModel):
    message_id: int
    rating: int


def warm_up() -> None:
    get_model()
    if not index_ready():
        logger.warning("no search index found; search routes will answer 503 until one is built or mounted")
    elif RETRIEVAL_MODE != "vector":
        get_keyword_index()
    if RETRIEVAL_MODE == "hybrid_rerank":
        get_reranker()
    get_provider()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    if os.getenv("SENTINEL_WARMUP", "on").lower() != "off":
        warm_up()
    yield


app = FastAPI(
    title="Sentinel API",
    description="Grounded, cited answers over a large codebase",
    version="0.3.0",
    lifespan=lifespan,
)


@app.exception_handler(IndexUnavailable)
async def index_unavailable_handler(_: Request, error: IndexUnavailable) -> JSONResponse:
    logger.warning("search index unavailable: %s", error)
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": INDEX_UNAVAILABLE_DETAIL})


app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)

protected = [Depends(require_api_key)]


def load_history(session_id: str | None) -> list[dict]:
    if session_id is None:
        return []

    if store.get_session(session_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")

    return store.recent_turns(session_id)


def record_query(session_id: str | None, question: str, payload: dict, message_id: int | None) -> None:
    store.add_query_log(
        session_id=session_id,
        question=question,
        standalone_question=payload.get("standalone_question", question),
        retrieved_ids=payload.get("retrieved_ids", []),
        retrieval_ms=payload.get("retrieval_ms", 0),
        generation_ms=payload.get("generation_ms", 0),
        model=payload.get("model", "unknown"),
        needs_review=(payload.get("checks") or {}).get("needs_review"),
        message_id=message_id,
    )


def save_turn(session_id: str | None, question: str, payload: dict) -> int | None:
    if not session_id:
        return None
    store.add_message(session_id, "user", question)
    return store.add_message(session_id, "assistant", payload["answer"], payload["sources"])


def guarded_payload(request: QueryRequest) -> dict | None:
    if injection_reason(request.question) is None:
        return None

    logger.warning("blocked a question that tries to override the instructions")
    return {
        "question": request.question,
        "standalone_question": request.question,
        "answer": BLOCKED_ANSWER,
        "sources": [],
        "top_k": request.top_k,
        "model": GUARDRAIL_MODEL_LABEL,
        "retrieval_ms": 0,
        "generation_ms": 0,
        "retrieved_ids": [],
    }


def canned_events(payload: dict) -> list[tuple[str, object]]:
    return [
        ("sources", {"sources": payload["sources"], "standalone_question": payload["standalone_question"]}),
        ("token", payload["answer"]),
        ("done", payload),
    ]


def sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="sentinel-api", index_ready=index_ready())


@app.get("/", response_model=RootResponse, dependencies=protected)
def root() -> RootResponse:
    return RootResponse(service="Sentinel API", status="running", docs="/docs", health="/health", query="/query")


@app.post("/query", response_model=QueryResponse, dependencies=protected)
def query(request: QueryRequest) -> QueryResponse:
    history = load_history(request.session_id)
    result = guarded_payload(request) or ask_sentinel(
        question=request.question,
        top_k=request.top_k,
        history=history,
        mode=request.mode,
        language=request.language,
        path_prefix=request.path_prefix,
    )

    message_id = save_turn(request.session_id, request.question, result)
    record_query(request.session_id, request.question, result, message_id)
    return QueryResponse(**result, session_id=request.session_id, message_id=message_id)


@app.post("/query/stream", dependencies=protected)
def query_stream(request: QueryRequest) -> StreamingResponse:
    history = load_history(request.session_id)

    def events() -> Iterator[str]:
        try:
            payload = guarded_payload(request)
            stream = iter(canned_events(payload)) if payload is not None else stream_sentinel(
                question=request.question,
                top_k=request.top_k,
                history=history,
                mode=request.mode,
                language=request.language,
                path_prefix=request.path_prefix,
            )
            for name, data in stream:
                if name == "done":
                    message_id = save_turn(request.session_id, request.question, data)
                    record_query(request.session_id, request.question, data, message_id)
                    data = {k: v for k, v in data.items() if k not in ("retrieved_ids", "standalone_question")}
                    data["message_id"] = message_id
                    data["session_id"] = request.session_id
                yield sse(name, data)
        except IndexUnavailable:
            yield sse("error", {"detail": INDEX_UNAVAILABLE_DETAIL})
        except Exception:
            logger.exception("streaming query failed")
            yield sse("error", {"detail": "The answer could not be generated. Please try again."})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/search", response_model=SearchResponse, dependencies=protected)
def search(request: QueryRequest) -> SearchResponse:
    results = retrieve(
        request.question,
        top_k=request.top_k,
        mode=request.mode,
        language=request.language,
        path_prefix=request.path_prefix,
    )

    return SearchResponse(
        question=request.question,
        top_k=request.top_k,
        results=[
            SourceItem(
                id=f"S{i}",
                path=item["metadata"].get("path"),
                language=item["metadata"].get("language"),
                title=item["metadata"].get("title"),
                distance=item.get("distance"),
                score=item.get("rerank_score", item.get("fusion_score", item.get("keyword_score"))),
                preview=item["content"][:800],
            )
            for i, item in enumerate(results, start=1)
        ],
    )


@app.post("/sessions", response_model=SessionCreated, status_code=status.HTTP_201_CREATED, dependencies=protected)
def create_session() -> SessionCreated:
    return SessionCreated(session_id=store.create_session())


@app.get("/sessions", response_model=list[SessionSummary], dependencies=protected)
def list_sessions(limit: int = Query(default=30, ge=1, le=100)) -> list[SessionSummary]:
    return [SessionSummary(**dict(row)) for row in store.list_sessions(limit)]


@app.get("/sessions/{session_id}", response_model=SessionDetail, dependencies=protected)
def get_session(session_id: str) -> SessionDetail:
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")

    messages = [
        MessageItem(
            id=row["id"],
            role=row["role"],
            content=row["content"],
            sources=json.loads(row["sources_json"]) if row["sources_json"] else None,
            created_at=row["created_at"],
        )
        for row in store.list_messages(session_id)
    ]
    return SessionDetail(
        id=session["id"],
        created_at=session["created_at"],
        last_active_at=session["last_active_at"],
        messages=messages,
    )


@app.post("/messages/{message_id}/feedback", response_model=FeedbackResponse, dependencies=protected)
def submit_feedback(message_id: int, request: FeedbackRequest) -> FeedbackResponse:
    message = store.get_message(message_id)
    if message is None or message["role"] != "assistant":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assistant message not found")

    store.add_feedback(message_id, request.rating)
    return FeedbackResponse(message_id=message_id, rating=request.rating)
