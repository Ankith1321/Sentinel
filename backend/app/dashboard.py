import json
import logging
import platform
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import torch
from pydantic import BaseModel

from backend.app import store
from backend.app.db import connect
from ingestion.config import (
    ANTHROPIC_MODEL,
    COLLECTION_NAME,
    EMBEDDING_MODEL,
    LOCAL_LLM_MODEL,
    LOCAL_LLM_QUANT,
    PROJECT_ROOT,
    PROMPT_VARIANT,
    RETRIEVAL_MODE,
    SUPERSET_REPO,
)
from ingestion.llm import resolve_provider_name
from ingestion.retriever import get_collection, keyword_index_size

RESULTS_DIR = PROJECT_ROOT / "eval" / "results"
PLAN_PATH = PROJECT_ROOT / "docs" / "06_IMPLEMENTATION_PLAN.md"
PHASE_HEADING = re.compile(r"^## (Phase [\d.]+) — (.+)$")
STATUS_LINE = re.compile(r"^\*\*Status: (.+?)\*\*")
RESULT_NAME = re.compile(r"^(\d{8}T\d{6}Z)_(.+)\.json$")
RECENT_LIMIT = 15
EVAL_LIMIT = 40

logger = logging.getLogger(__name__)


class GpuInfo(BaseModel):
    name: str
    memory_used_mb: int
    memory_total_mb: int


class ServiceInfo(BaseModel):
    started_at: str
    uptime_seconds: int
    provider: str
    model: str
    quantization: str | None = None
    prompt_variant: str
    retrieval_mode: str
    embedding_model: str
    collection: str
    chunks_in_index: int | None = None
    keyword_index_chunks: int | None = None
    gpu: GpuInfo | None = None
    python_version: str
    torch_version: str


class SyncRunSummary(BaseModel):
    id: int
    status: str
    pulled: bool
    commit_before: str | None = None
    commit_after: str | None = None
    added: int | None = None
    changed: int | None = None
    removed: int | None = None
    unchanged: int | None = None
    error_count: int = 0
    error: str | None = None
    started_at: str
    finished_at: str | None = None


class CorpusInfo(BaseModel):
    path: str
    commit: str | None = None
    commit_subject: str | None = None
    files_tracked: int
    chunks_tracked: int
    uploaded_files: int
    sync_runs: list[SyncRunSummary]


class DayCount(BaseModel):
    day: str
    queries: int


class UsageInfo(BaseModel):
    queries: int
    avg_retrieval_ms: int
    avg_generation_ms: int
    p95_total_ms: int
    flagged: int
    checked: int
    sessions: int
    feedback_up: int
    feedback_down: int
    feedback_positive_ratio: float | None = None
    queries_per_day: list[DayCount]


class RecentQuery(BaseModel):
    message_id: int | None = None
    verified_answer_id: int | None = None
    created_at: str
    question: str
    model: str
    retrieval_ms: int
    generation_ms: int
    needs_review: bool | None = None


class UploadJob(BaseModel):
    filename: str
    status: str
    error: str | None = None
    created_at: str
    finished_at: str | None = None


class RetrievalRun(BaseModel):
    label: str
    created_at: str
    mode: str | None = None
    collection: str | None = None
    embedding_model: str | None = None
    questions: int
    hit_at_1: float
    hit_at_5: float
    hit_at_10: float
    mrr: float


class AnswerRun(BaseModel):
    label: str
    created_at: str
    model: str | None = None
    quantization: str | None = None
    prompt: str | None = None
    cites_a_source: float
    cites_expected_file: float
    refuses_off_topic: float
    flagged: float
    avg_seconds: float


class PlanPhase(BaseModel):
    phase: str
    title: str
    status: str
    state: str


class Commit(BaseModel):
    hash: str
    date: str
    subject: str


class VerifiedSummary(BaseModel):
    pending: int
    approved: int
    stale: int
    rejected: int
    served: int


class DashboardResponse(BaseModel):
    generated_at: str
    service: ServiceInfo
    corpus: CorpusInfo
    usage: UsageInfo
    recent_queries: list[RecentQuery]
    verified: VerifiedSummary
    uploads: list[UploadJob]
    retrieval_runs: list[RetrievalRun]
    answer_runs: list[AnswerRun]
    plan: list[PlanPhase]
    commits: list[Commit]


def git_lines(repo: Path, *args: str) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return result.stdout.splitlines() if result.returncode == 0 else []


def index_chunk_count() -> int | None:
    try:
        return get_collection().count()
    except Exception:
        logger.warning("vector index unavailable for the dashboard", exc_info=True)
        return None


def gpu_info() -> GpuInfo | None:
    if not torch.cuda.is_available():
        return None
    free, total = torch.cuda.mem_get_info()
    return GpuInfo(
        name=torch.cuda.get_device_name(0),
        memory_used_mb=(total - free) // 2**20,
        memory_total_mb=total // 2**20,
    )


def service_info(started_at: datetime) -> ServiceInfo:
    provider = resolve_provider_name()
    return ServiceInfo(
        started_at=started_at.isoformat(),
        uptime_seconds=int((datetime.now(timezone.utc) - started_at).total_seconds()),
        provider=provider,
        model=ANTHROPIC_MODEL if provider == "anthropic" else LOCAL_LLM_MODEL,
        quantization=None if provider == "anthropic" else (LOCAL_LLM_QUANT or "fp16"),
        prompt_variant=PROMPT_VARIANT,
        retrieval_mode=RETRIEVAL_MODE,
        embedding_model=EMBEDDING_MODEL,
        collection=COLLECTION_NAME,
        chunks_in_index=index_chunk_count(),
        keyword_index_chunks=keyword_index_size(),
        gpu=gpu_info(),
        python_version=platform.python_version(),
        torch_version=torch.__version__,
    )


def corpus_info() -> CorpusInfo:
    counts = store.document_counts()
    head = git_lines(SUPERSET_REPO, "log", "-1", "--format=%h %cs|%s")
    commit, _, subject = head[0].partition("|") if head else (None, "", None)
    runs = [
        SyncRunSummary(
            **{k: row[k] for k in SyncRunSummary.model_fields if k in row.keys() and k != "error_count"},
            error_count=len(json.loads(row["errors_json"] or "[]")),
        )
        for row in store.recent_sync_runs(5)
    ]
    return CorpusInfo(
        path=str(SUPERSET_REPO),
        commit=commit,
        commit_subject=subject or None,
        files_tracked=counts.get("code_files", 0),
        chunks_tracked=counts.get("code_chunks", 0),
        uploaded_files=counts.get(f"{store.UPLOAD_SOURCE}_files", 0),
        sync_runs=runs,
    )


def usage_info() -> UsageInfo:
    stats = store.query_stats()
    with connect() as db:
        flagged, checked = db.execute(
            "SELECT COALESCE(SUM(needs_review = 1), 0), COUNT(needs_review) FROM query_log"
        ).fetchone()
        sessions = db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    return UsageInfo(**stats, flagged=flagged, checked=checked, sessions=sessions)


def recent_queries() -> list[RecentQuery]:
    with connect() as db:
        rows = db.execute(
            "SELECT message_id, verified_answer_id, created_at, question, model, retrieval_ms, generation_ms, "
            "needs_review "
            "FROM query_log ORDER BY id DESC LIMIT ?",
            (RECENT_LIMIT,),
        ).fetchall()
    return [
        RecentQuery(**{**dict(r), "needs_review": None if r["needs_review"] is None else bool(r["needs_review"])})
        for r in rows
    ]


def verified_summary() -> VerifiedSummary:
    with connect() as db:
        served = db.execute("SELECT COALESCE(SUM(times_served), 0) FROM verified_answers").fetchone()[0]
    return VerifiedSummary(**store.verified_answer_counts(), served=served)


def recent_uploads() -> list[UploadJob]:
    with connect() as db:
        rows = db.execute(
            "SELECT filename, status, error, created_at, finished_at FROM jobs ORDER BY created_at DESC LIMIT ?",
            (RECENT_LIMIT,),
        ).fetchall()
    return [UploadJob(**dict(r)) for r in rows]


def stamp_to_iso(stamp: str) -> str:
    return datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()


def eval_runs() -> tuple[list[RetrievalRun], list[AnswerRun]]:
    retrieval: list[RetrievalRun] = []
    answers: list[AnswerRun] = []
    if not RESULTS_DIR.is_dir():
        return retrieval, answers

    for path in sorted(RESULTS_DIR.glob("*.json"), reverse=True):
        match = RESULT_NAME.match(path.name)
        if not match:
            continue
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        created, label = stamp_to_iso(match.group(1)), match.group(2)
        summary, config = report.get("summary", {}), report.get("config", {})

        if "overall" in summary and len(retrieval) < EVAL_LIMIT:
            o = summary["overall"]
            retrieval.append(RetrievalRun(
                label=label, created_at=created, mode=config.get("mode"), collection=config.get("collection"),
                embedding_model=config.get("embedding_model"), questions=o["n"], hit_at_1=o["hit@1"],
                hit_at_5=o["hit@5"], hit_at_10=o["hit@10"], mrr=o["mrr"],
            ))
        elif "answerable_n" in summary and len(answers) < EVAL_LIMIT:
            answers.append(AnswerRun(
                label=label, created_at=created, model=config.get("model"), quantization=config.get("quantization"),
                prompt=config.get("prompt"), cites_a_source=summary["cites_a_source"],
                cites_expected_file=summary["cites_expected_file_when_retrieved"],
                refuses_off_topic=summary["correctly_abstained_on_unanswerable"],
                flagged=summary["flagged_needs_review"], avg_seconds=summary["avg_seconds"],
            ))

    return retrieval, answers


def phase_state(status: str) -> str:
    lowered = status.lower()
    if lowered.startswith("done") and not any(word in lowered for word in ("gap", "but", "except")):
        return "done"
    if lowered.startswith(("done", "partly", "partial")):
        return "partial"
    return "todo"


def plan_phases() -> list[PlanPhase]:
    try:
        lines = PLAN_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    phases: list[PlanPhase] = []
    current: tuple[str, str] | None = None
    for line in lines:
        heading = PHASE_HEADING.match(line)
        if heading:
            if current:
                phases.append(PlanPhase(phase=current[0], title=current[1], status="Not started", state="todo"))
            current = (heading.group(1), heading.group(2))
            continue
        status = STATUS_LINE.match(line)
        if status and current:
            text = status.group(1).rstrip(".")
            phases.append(PlanPhase(phase=current[0], title=current[1], status=text, state=phase_state(text)))
            current = None
    if current:
        phases.append(PlanPhase(phase=current[0], title=current[1], status="Not started", state="todo"))
    return phases


def project_commits() -> list[Commit]:
    commits = []
    for line in git_lines(PROJECT_ROOT, "log", "-10", "--format=%h|%cs|%s"):
        short, date, subject = (line.split("|", 2) + ["", ""])[:3]
        commits.append(Commit(hash=short, date=date, subject=subject))
    return commits


def build_dashboard(started_at: datetime) -> DashboardResponse:
    retrieval, answers = eval_runs()
    return DashboardResponse(
        generated_at=datetime.now(timezone.utc).isoformat(),
        service=service_info(started_at),
        corpus=corpus_info(),
        usage=usage_info(),
        recent_queries=recent_queries(),
        verified=verified_summary(),
        uploads=recent_uploads(),
        retrieval_runs=retrieval,
        answer_runs=answers,
        plan=plan_phases(),
        commits=project_commits(),
    )
