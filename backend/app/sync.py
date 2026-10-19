import argparse
import logging
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from backend.app import store
from backend.app.db import init_db
from backend.app.documents import replace_source_chunks
from ingestion.chunker import chunk_record
from ingestion.config import SUPERSET_REPO
from ingestion.file_scanner import scan_source_files
from ingestion.loader import load_file
from ingestion.retriever import get_collection, refresh_keyword_index

GIT_TIMEOUT_SECONDS = 600

logger = logging.getLogger(__name__)

_sync_lock = threading.Lock()


class SyncInProgress(RuntimeError):
    pass


@dataclass
class SyncReport:
    commit_before: str | None = None
    commit_after: str | None = None
    scanned: int = 0
    added: int = 0
    changed: int = 0
    removed: int = 0
    unchanged: int = 0
    chunks_written: int = 0
    chunks_deleted: int = 0
    seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def touched(self) -> bool:
        return bool(self.added or self.changed or self.removed)

    def to_dict(self) -> dict:
        return asdict(self)


def sync_running() -> bool:
    return _sync_lock.locked()


def git_head(repo: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repo), "log", "-1", "--format=%h %cs"], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() or None if result.returncode == 0 else None


def git_pull(repo: Path) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "pull", "--ff-only"],
        capture_output=True,
        text=True,
        check=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )


def index_changed_files(root: Path, manifest: dict, report: SyncReport) -> set[str]:
    seen: set[str] = set()

    for path in scan_source_files(root):
        report.scanned += 1
        relative = path.relative_to(root).as_posix()
        seen.add(relative)

        try:
            record = load_file(path, root)
            if record is None:
                seen.discard(relative)
                continue

            known = manifest.get(relative)
            if known is not None and known["content_hash"] == record.content_hash:
                report.unchanged += 1
                continue

            written, deleted = replace_source_chunks(record.source_id, chunk_record(record))
            store.upsert_document(
                record.source_id, relative, record.source_type, record.language, record.content_hash, written
            )
            report.chunks_written += written
            report.chunks_deleted += deleted
            if known is None:
                report.added += 1
            else:
                report.changed += 1
        except Exception as error:
            logger.exception("sync failed for %s", relative)
            report.errors.append(f"{relative}: {error}")

    return seen


def remove_missing_files(manifest: dict, seen: set[str], report: SyncReport) -> None:
    for relative, row in manifest.items():
        if relative in seen:
            continue
        stale = get_collection().get(where={"source_id": row["id"]}, include=[])["ids"]
        if stale:
            get_collection().delete(ids=stale)
        store.delete_document(row["id"])
        report.chunks_deleted += len(stale)
        report.removed += 1


def sync_corpus(root: Path = SUPERSET_REPO, pull: bool = False, refresh_keywords: bool = True) -> SyncReport:
    if not _sync_lock.acquire(blocking=False):
        raise SyncInProgress("A sync is already running")

    started = time.perf_counter()
    report = SyncReport()
    try:
        report.commit_before = git_head(root)
        if pull:
            try:
                git_pull(root)
            except (subprocess.SubprocessError, OSError) as error:
                report.errors.append(f"git pull failed, indexing the current checkout instead: {error}")
        report.commit_after = git_head(root)

        manifest = store.corpus_documents()
        seen = index_changed_files(root, manifest, report)
        remove_missing_files(manifest, seen, report)

        if report.touched and refresh_keywords:
            refresh_keyword_index()
        return report
    finally:
        report.seconds = round(time.perf_counter() - started, 1)
        _sync_lock.release()


def run_sync_job(run_id: int, pull: bool, refresh_keywords: bool = True) -> None:
    try:
        report = sync_corpus(pull=pull, refresh_keywords=refresh_keywords)
    except Exception as error:
        logger.exception("sync run %d failed", run_id)
        store.finish_sync_run(run_id, None, str(error))
        return

    store.finish_sync_run(run_id, report.to_dict(), None)
    logger.info("sync run %d: %s", run_id, report.to_dict())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bring the index up to date with the corpus. Do not run while the API is serving; "
        "use POST /admin/sync instead, so only one process writes to the index."
    )
    parser.add_argument("--pull", action="store_true", help="git pull --ff-only the corpus first")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    init_db()
    run_id = store.start_sync_run(args.pull)
    # A standalone process exits right after, so rebuilding the in-memory keyword index would be wasted.
    run_sync_job(run_id, args.pull, refresh_keywords=False)
    row = store.recent_sync_runs(1)[0]
    return 0 if row["status"] == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
