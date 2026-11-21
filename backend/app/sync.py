import argparse
import logging
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from backend.app import store
from backend.app.db import init_db
from ingestion.chunker import ChunkRecord, chunk_record
from ingestion.config import SUPERSET_REPO
from ingestion.file_scanner import scan_source_files
from ingestion.loader import load_file
from ingestion.retriever import get_collection, get_model

GIT_TIMEOUT_SECONDS = 600
EMBED_BATCH_SIZE = 64

logger = logging.getLogger(__name__)


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

    def to_dict(self) -> dict:
        return asdict(self)


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


def embed_and_upsert(chunks: list[ChunkRecord]) -> None:
    collection = get_collection()
    model = get_model()

    for start in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = chunks[start:start + EMBED_BATCH_SIZE]
        texts = [c.content for c in batch]
        embeddings = model.encode(texts, batch_size=EMBED_BATCH_SIZE, normalize_embeddings=True).tolist()

        collection.upsert(
            ids=[c.chunk_id for c in batch],
            documents=texts,
            embeddings=embeddings,
            metadatas=[
                {
                    "source_id": c.source_id,
                    "source_type": c.source_type,
                    "path": c.path,
                    "language": c.language,
                    "title": c.title or "",
                    "chunk_index": c.chunk_index,
                }
                for c in batch
            ],
        )


def replace_source_chunks(source_id: str, chunks: list[ChunkRecord]) -> tuple[int, int]:
    # Upsert first, then delete what the new version no longer produces, so a search never
    # sees the file missing and a shrunken file leaves no stale chunks behind.
    if chunks:
        embed_and_upsert(chunks)
    keep = {c.chunk_id for c in chunks}
    stale = [i for i in get_collection().get(where={"source_id": source_id}, include=[])["ids"] if i not in keep]
    if stale:
        get_collection().delete(ids=stale)
    return len(chunks), len(stale)


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


def sync_corpus(root: Path = SUPERSET_REPO, pull: bool = False) -> SyncReport:
    started = time.perf_counter()
    report = SyncReport()

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

    report.seconds = round(time.perf_counter() - started, 1)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bring the index up to date with the corpus. Stop the API first: only one process may "
        "write to the index, and a running API keeps its keyword index in memory until it restarts."
    )
    parser.add_argument("--pull", action="store_true", help="git pull --ff-only the corpus first")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    init_db()
    report = sync_corpus(pull=args.pull)
    logger.info("sync finished: %s", report.to_dict())
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
