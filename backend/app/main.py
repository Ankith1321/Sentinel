import json
import logging
import os
import time
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.app import store, verified
from backend.app.auth import require_admin_key, require_api_key
from backend.app.dashboard import DashboardResponse, build_dashboard
from backend.app.db import init_db
from backend.app.documents import SUPPORTED_UPLOAD_SUFFIXES, delete_indexed_document, ingest_upload, safe_filename
from backend.app.snapshot import export_snapshot, import_if_empty
from backend.app.sync import run_sync_job, sync_running
from ingestion.config import CORS_ORIGINS, LOG_LEVEL, MAX_UPLOAD_BYTES, PROJECT_ROOT, RETRIEVAL_MODE
from ingestion.llm import get_provider
from ingestion.rag_service import ask_sentinel, reformulate_question, stream_sentinel
from ingestion.retriever import get_keyword_index, get_model, get_reranker, refresh_keyword_index, retrieve

logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
for noisy in ("httpx", "httpcore", "huggingface_hub", "sentence_transformers", "urllib3", "filelock"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

STARTED_AT = datetime.now(timezone.utc)

Language = Literal["python", "markdown", "javascript", "typescript", "text"]
RetrievalMode = Literal["vector", "keyword", "hybrid", "hybrid_rerank"]
DocumentSource = Literal["upload", "corpus"]
VerifiedStatus = Literal["pending", "approved", "stale", "rejected"]
Question = Annotated[str, Field(min_length=3, max_length=2000)]
VERIFIED_MODEL_LABEL = "verified-answer"
SEED_QUESTIONS_PATH = PROJECT_ROOT / "eval" / "verified_seed_questions.json"


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


class VerifiedInfo(BaseModel):
    id: int
    similarity: float
    matched_question: str
    reviewed_at: str | None = None


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
    verified: VerifiedInfo | None = None
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


class VerifiedItem(BaseModel):
    id: int
    question: str
    answer: str
    sources: list[SourceItem]
    status: VerifiedStatus
    origin: str
    stale_reason: str | None = None
    times_served: int
    created_at: str
    reviewed_at: str | None = None
    last_served_at: str | None = None


class VerifiedList(BaseModel):
    total: int
    counts: dict[str, int]
    items: list[VerifiedItem]


class DraftRequest(BaseModel):
    questions: list[Question] = Field(..., min_length=1, max_length=100)


class DraftsQueued(BaseModel):
    queued: int


class ApproveRequest(BaseModel):
    answer: str | None = Field(default=None, min_length=3, max_length=8000)


class VerifiedCreated(BaseModel):
    id: int


class SkippedApproval(BaseModel):
    id: int
    question: str
    reason: str


class BulkApproval(BaseModel):
    approved: int
    skipped: list[SkippedApproval]


class SnapshotExport(BaseModel):
    exported: int
    path: str


class AdminSession(BaseModel):
    admin: bool


def to_verified_item(row) -> VerifiedItem:
    data = {k: row[k] for k in row.keys() if k not in ("sources_json", "source_hashes_json")}
    return VerifiedItem(**data, sources=json.loads(row["sources_json"]))


class SyncStarted(BaseModel):
    run_id: int
    status: str


class SyncRun(BaseModel):
    id: int
    status: str
    pulled: bool
    commit_before: str | None = None
    commit_after: str | None = None
    scanned: int | None = None
    added: int | None = None
    changed: int | None = None
    removed: int | None = None
    unchanged: int | None = None
    chunks_written: int | None = None
    chunks_deleted: int | None = None
    verified_stale: int | None = None
    errors: list[str] = []
    error: str | None = None
    started_at: str
    finished_at: str | None = None


def to_sync_run(row) -> SyncRun:
    data = dict(row)
    data["errors"] = json.loads(data.pop("errors_json") or "[]")
    data["pulled"] = bool(data["pulled"])
    return SyncRun(**data)


class DeleteResponse(BaseModel):
    id: str
    deleted: bool


class DayCount(BaseModel):
    day: str
    queries: int


class StatsResponse(BaseModel):
    queries: int
    avg_retrieval_ms: int
    avg_generation_ms: int
    p95_total_ms: int
    feedback_up: int
    feedback_down: int
    feedback_positive_ratio: float | None = None
    queries_per_day: list[DayCount]


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
    imported = import_if_empty()
    if imported:
        logger.info("loaded %d verified answers from the snapshot", imported)
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
        verified_answer_id=(payload.get("verified") or {}).get("id"),
    )


def save_turn(session_id: str | None, question: str, payload: dict) -> int | None:
    if not session_id:
        return None
    store.add_message(session_id, "user", question)
    return store.add_message(session_id, "assistant", payload["answer"], payload["sources"])


def resolve_question(request: QueryRequest, history: list[dict]) -> tuple[str, verified.VerifiedMatch | None]:
    standalone = reformulate_question(request.question, history)
    if request.language or request.path_prefix or request.mode:
        return standalone, None
    return standalone, verified.find_match(standalone)


def verified_payload(request: QueryRequest, standalone: str, match: verified.VerifiedMatch, started: float) -> dict:
    store.record_verified_served(match.id)
    return {
        "question": request.question,
        "standalone_question": standalone,
        "answer": match.answer,
        "sources": match.sources,
        "top_k": request.top_k,
        "model": VERIFIED_MODEL_LABEL,
        "retrieval_ms": round((time.perf_counter() - started) * 1000),
        "generation_ms": 0,
        "retrieved_ids": [],
        "verified": {
            "id": match.id,
            "similarity": match.similarity,
            "matched_question": match.question,
            "reviewed_at": match.reviewed_at,
        },
    }


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
    started = time.perf_counter()
    standalone, match = resolve_question(request, history)

    if match:
        result = verified_payload(request, standalone, match, started)
    else:
        result = ask_sentinel(
            question=request.question,
            top_k=request.top_k,
            history=history,
            mode=request.mode,
            language=request.language,
            path_prefix=request.path_prefix,
            standalone_question=standalone,
        )

    message_id = save_turn(request.session_id, request.question, result)
    record_query(request.session_id, request.question, result, message_id)
    return QueryResponse(**result, session_id=request.session_id, message_id=message_id)


@app.post("/query/stream", dependencies=protected)
def query_stream(request: QueryRequest) -> StreamingResponse:
    history = load_history(request.session_id)

    def events() -> Iterator[str]:
        try:
            started = time.perf_counter()
            standalone, match = resolve_question(request, history)
            if match:
                payload = verified_payload(request, standalone, match, started)
                stream = iter([
                    ("sources", {"sources": payload["sources"], "standalone_question": standalone}),
                    ("token", payload["answer"]),
                    ("done", payload),
                ])
            else:
                stream = stream_sentinel(
                    question=request.question,
                    top_k=request.top_k,
                    history=history,
                    mode=request.mode,
                    language=request.language,
                    path_prefix=request.path_prefix,
                    standalone_question=standalone,
                )
            for name, data in stream:
                if name == "done":
                    message_id = save_turn(request.session_id, request.question, data)
                    record_query(request.session_id, request.question, data, message_id)
                    data = {k: v for k, v in data.items() if k not in ("retrieved_ids", "standalone_question")}
                    data["message_id"] = message_id
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
    source: DocumentSource | None = None,
) -> DocumentList:
    rows, total = store.list_documents(limit, offset, source)
    return DocumentList(total=total, items=[DocumentItem(**dict(row)) for row in rows])


@app.delete("/documents/{document_id}", response_model=DeleteResponse, dependencies=protected)
def delete_document(document_id: str, background_tasks: BackgroundTasks) -> DeleteResponse:
    if not delete_indexed_document(document_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    background_tasks.add_task(refresh_keyword_index)
    return DeleteResponse(id=document_id, deleted=True)


@app.get("/admin/session", response_model=AdminSession, dependencies=admin_only)
def admin_session() -> AdminSession:
    return AdminSession(admin=True)


@app.get("/admin/dashboard", response_model=DashboardResponse, dependencies=admin_only)
def dashboard() -> DashboardResponse:
    return build_dashboard(STARTED_AT)


@app.get("/admin/verified", response_model=VerifiedList, dependencies=admin_only)
def list_verified(
    status_filter: VerifiedStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> VerifiedList:
    rows, total = store.list_verified_answers(status_filter, limit, offset)
    return VerifiedList(total=total, counts=store.verified_answer_counts(), items=[to_verified_item(r) for r in rows])


@app.get("/admin/verified/seeds", response_model=list[str], dependencies=admin_only)
def seed_questions() -> list[str]:
    try:
        seeds = json.loads(SEED_QUESTIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows, _ = store.list_verified_answers(None, 10_000, 0)
    known = {r["question"].lower() for r in rows if r["status"] != "rejected"}
    return [q for q in seeds if q.lower() not in known]


def draft_answers(questions: list[str]) -> None:
    for question in questions:
        try:
            result = ask_sentinel(question=question, top_k=5)
            store.create_verified_answer(question, result["answer"], result["sources"], "generated")
        except Exception:
            logger.exception("drafting a verified answer failed for %r", question)


@app.post(
    "/admin/verified/drafts", response_model=DraftsQueued, status_code=status.HTTP_202_ACCEPTED, dependencies=admin_only
)
def queue_drafts(request: DraftRequest, background_tasks: BackgroundTasks) -> DraftsQueued:
    background_tasks.add_task(draft_answers, request.questions)
    return DraftsQueued(queued=len(request.questions))


@app.post(
    "/admin/verified/from-message/{message_id}",
    response_model=VerifiedCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=admin_only,
)
def verified_from_message(message_id: int) -> VerifiedCreated:
    turn = store.assistant_turn(message_id)
    if turn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assistant message not found")
    question, answer = turn
    sources = json.loads(answer["sources_json"]) if answer["sources_json"] else []
    created = store.create_verified_answer(question, answer["content"], sources, "chat")
    if created is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This question already has a verified answer")
    return VerifiedCreated(id=created)


@app.post("/admin/verified/approve-all", response_model=BulkApproval, dependencies=admin_only)
def approve_all_verified() -> BulkApproval:
    approved, skipped = verified.approve_all_pending()
    export_snapshot()
    return BulkApproval(approved=len(approved), skipped=[SkippedApproval(**s) for s in skipped])


@app.post("/admin/verified/export", response_model=SnapshotExport, dependencies=admin_only)
def export_verified() -> SnapshotExport:
    count = export_snapshot()
    return SnapshotExport(exported=count, path="data/verified_answers.json")


@app.post("/admin/verified/{answer_id}/approve", response_model=VerifiedItem, dependencies=admin_only)
def approve_verified(answer_id: int, request: ApproveRequest) -> VerifiedItem:
    try:
        verified.approve(answer_id, request.answer)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Verified answer not found") from None
    except verified.ApprovalRejected as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    export_snapshot()
    return to_verified_item(store.get_verified_answer(answer_id))


@app.post("/admin/verified/{answer_id}/reject", response_model=VerifiedItem, dependencies=admin_only)
def reject_verified(answer_id: int) -> VerifiedItem:
    try:
        verified.set_status(answer_id, "rejected")
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Verified answer not found") from None
    export_snapshot()
    return to_verified_item(store.get_verified_answer(answer_id))


@app.delete("/admin/verified/{answer_id}", response_model=DeleteResponse, dependencies=admin_only)
def delete_verified(answer_id: int) -> DeleteResponse:
    if not verified.remove(answer_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Verified answer not found")
    export_snapshot()
    return DeleteResponse(id=str(answer_id), deleted=True)


@app.post("/admin/sync", response_model=SyncStarted, status_code=status.HTTP_202_ACCEPTED, dependencies=admin_only)
def start_sync(background_tasks: BackgroundTasks, pull: bool = False) -> SyncStarted:
    if sync_running():
        raise HTTPException(status.HTTP_409_CONFLICT, "A sync is already running")

    run_id = store.start_sync_run(pull)
    background_tasks.add_task(run_sync_job, run_id, pull)
    return SyncStarted(run_id=run_id, status="running")


@app.get("/admin/sync", response_model=list[SyncRun], dependencies=admin_only)
def list_sync_runs(limit: int = Query(default=10, ge=1, le=50)) -> list[SyncRun]:
    return [to_sync_run(row) for row in store.recent_sync_runs(limit)]


@app.post("/admin/keys", response_model=KeyCreated, status_code=status.HTTP_201_CREATED, dependencies=admin_only)
def create_key(request: KeyCreateRequest) -> KeyCreated:
    key_id, raw_key = store.create_api_key(request.label)
    return KeyCreated(id=key_id, label=request.label, key=raw_key)


@app.get("/admin/stats", response_model=StatsResponse, dependencies=admin_only)
def stats() -> StatsResponse:
    return StatsResponse(**store.query_stats())


@app.get("/admin/keys", response_model=list[KeyItem], dependencies=admin_only)
def list_keys() -> list[KeyItem]:
    return [KeyItem(**dict(row)) for row in store.list_api_keys()]


@app.delete("/admin/keys/{key_id}", response_model=DeleteResponse, dependencies=admin_only)
def revoke_key(key_id: str) -> DeleteResponse:
    if not store.revoke_api_key(key_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Key not found or already revoked")

    return DeleteResponse(id=key_id, deleted=True)
