from pathlib import Path
from uuid import uuid4

from ingestion.file_scanner import scan_source_files, detect_language
from ingestion.records import SourceRecord


def load_file(path: Path) -> SourceRecord | None:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None

    text = text.strip()

    if not text:
        return None

    return SourceRecord(
        source_id=str(uuid4()),
        source_type="code",
        path=str(path),
        language=detect_language(path),
        title=path.name,
        content=text,
    )


def load_all_records():
    files = scan_source_files()

    records = []

    for path in files:
        record = load_file(path)

        if record:
            records.append(record)

    return records


if __name__ == "__main__":
    records = load_all_records()

    print(f"Loaded {len(records)} records")

    for r in records[:3]:
        print("=" * 80)
        print("TITLE:", r.title)
        print("LANGUAGE:", r.language)
        print("PATH:", r.path)
        print("CONTENT SAMPLE:")
        print(r.content[:500])