import hashlib
from pathlib import Path

from ingestion.config import SUPERSET_REPO
from ingestion.file_scanner import detect_language, scan_source_files
from ingestion.records import SourceRecord


def stable_source_id(relative_path: str) -> str:
    return hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:32]


def load_file(path: Path, root: Path = SUPERSET_REPO) -> SourceRecord | None:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None

    text = text.strip()

    if not text:
        return None

    relative_path = path.relative_to(root).as_posix()

    return SourceRecord(
        source_id=stable_source_id(relative_path),
        source_type="code",
        path=relative_path,
        language=detect_language(path),
        title=path.name,
        content=text,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def load_all_records():
    files = scan_source_files()

    records = []

    for path in files:
        record = load_file(path)

        if record:
            records.append(record)

    return records

