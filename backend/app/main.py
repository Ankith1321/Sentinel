import json
import logging
import os
from collections.abc import Iterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.app import store
from backend.app.auth import require_admin_key, require_api_key
from backend.app.db import init_db
from backend.app.documents import SUPPORTED_UPLOAD_SUFFIXES, delete_indexed_document, ingest_upload, safe_filename
from ingestion.config import CORS_ORIGINS, MAX_UPLOAD_BYTES, RETRIEVAL_MODE
from ingestion.llm import get_provider
from ingestion.rag_service import ask_sentinel, stream_sentinel
from ingestion.retriever import get_keyword_index, get_model, get_reranker, retrieve

logger = logging.getLogger(__name__)

Language = Literal["python", "markdown", "javascript", "typescript", "text"]
RetrievalMode = Literal["vector", "keyword", "hybrid", "hybrid_rerank"]


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


class QueryResponse(BaseModel):
    question: str
    standalone_question: str
    answer: str
    sources: list[SourceItem]
    top_k: int
    model: str
    retrieval_ms: int
    generation_ms: int
    session_id: str | None = None
    message_id: int | None = None


class SearchResponse(BaseModel):
    question: str
    top_k: int
    results: list[SourceItem]


class HealthResponse(BaseModel):
    status: str
    service: str


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


class UploadResponse(BaseModel):
    job_id: str
    filename: str
    status: str


class JobStatus(BaseModel):
    id: str
    filename: str
    status: str
    document_id: str | None = None
    error: str | None = None
    created_at: str
    finished_at: str | None = None


class DocumentItem(BaseModel):
    id: str
    path: str
    source_type: str
    language: str | None = None
    content_hash: str
    chunk_count: int
    first_indexed_at: str
    last_indexed_at: str


class DocumentList(BaseModel):
    total: int
    items: list[DocumentItem]


class DeleteResponse(BaseModel):
    id: str
    deleted: bool


class KeyCreateRequest(BaseModel):
    label: str | None = Field(default=None, max_length=80)


class KeyCreated(BaseModel):
    id: str
    label: str | None = None
    key: str


class KeyItem(BaseModel):
    id: str
    label: str | None = None
    created_at: str
    revoked_at: str | None = None


def warm_up() -> None:
    get_model()
    if RETRIEVAL_MODE != "vector":
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
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "X-API-Key"],
)

protected = [Depends(require_api_key)]
admin_only = [Depends(require_admin_key)]


def load_history(session_id: str | None) -> list[dict]:
    if session_id is None:
        return []

    if store.get_session(session_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")

    return store.recent_turns(session_id)


def sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="sentinel-api")


@app.get("/", response_model=RootResponse, dependencies=protected)
def root() -> RootResponse:
    return RootResponse(service="Sentinel API", status="running", docs="/docs", health="/health", query="/query")


@app.post("/query", response_model=QueryResponse, dependencies=protected)
def query(request: QueryRequest) -> QueryResponse:
    history = load_history(request.session_id)

    result = ask_sentinel(
        question=request.question,
        top_k=request.top_k,
        history=history,
        mode=request.mode,
        language=request.language,
        path_prefix=request.path_prefix,
    )

    message_id = None
    if request.session_id:
        store.add_message(request.session_id, "user", request.question)
        message_id = store.add_message(request.session_id, "assistant", result["answer"], result["sources"])

    return QueryResponse(**result, session_id=request.session_id, message_id=message_id)


@app.post("/query/stream", dependencies=protected)
def query_stream(request: QueryRequest) -> StreamingResponse:
    history = load_history(request.session_id)

    def events() -> Iterator[str]:
        try:
            for name, data in stream_sentinel(
                question=request.question,
                top_k=request.top_k,
                history=history,
                mode=request.mode,
                language=request.language,
                path_prefix=request.path_prefix,
            ):
                if name == "done" and request.session_id:
                    store.add_message(request.session_id, "user", request.question)
                    data["message_id"] = store.add_message(
                        request.session_id, "assistant", data["answer"], data["sources"]
                    )
                    data["session_id"] = request.session_id
                yield sse(name, data)
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


@app.post(
    "/documents/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=protected,
)
async def upload_document(background_tasks: BackgroundTasks, file: UploadFile = File(...)) -> UploadResponse:
    filename = safe_filename(file.filename or "")
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Unsupported file type. Allowed: {', '.join(sorted(SUPPORTED_UPLOAD_SUFFIXES))}",
        )

    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"File exceeds {MAX_UPLOAD_BYTES} bytes")

    job_id = store.create_job(filename)
    background_tasks.add_task(ingest_upload, job_id, filename, data)
    return UploadResponse(job_id=job_id, filename=filename, status="queued")


@app.get("/jobs/{job_id}", response_model=JobStatus, dependencies=protected)
def get_job(job_id: str) -> JobStatus:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")

    return JobStatus(**dict(job))


@app.get("/documents", response_model=DocumentList, dependencies=protected)
def list_documents(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> DocumentList:
    rows, total = store.list_documents(limit, offset)
    return DocumentList(total=total, items=[DocumentItem(**dict(row)) for row in rows])


@app.delete("/documents/{document_id}", response_model=DeleteResponse, dependencies=protected)
def delete_document(document_id: str) -> DeleteResponse:
    if not delete_indexed_document(document_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    return DeleteResponse(id=document_id, deleted=True)


@app.post("/admin/keys", response_model=KeyCreated, status_code=status.HTTP_201_CREATED, dependencies=admin_only)
def create_key(request: KeyCreateRequest) -> KeyCreated:
    key_id, raw_key = store.create_api_key(request.label)
    return KeyCreated(id=key_id, label=request.label, key=raw_key)


@app.get("/admin/keys", response_model=list[KeyItem], dependencies=admin_only)
def list_keys() -> list[KeyItem]:
    return [KeyItem(**dict(row)) for row in store.list_api_keys()]


@app.delete("/admin/keys/{key_id}", response_model=DeleteResponse, dependencies=admin_only)
def revoke_key(key_id: str) -> DeleteResponse:
    if not store.revoke_api_key(key_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Key not found or already revoked")

    return DeleteResponse(id=key_id, deleted=True)
