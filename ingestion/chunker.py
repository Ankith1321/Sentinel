import re
from dataclasses import dataclass, asdict
from typing import Optional

from ingestion.loader import load_all_records


@dataclass
class ChunkRecord:
    chunk_id: str
    source_id: str
    source_type: str
    path: str
    language: str
    title: Optional[str]
    chunk_index: int
    content: str

    def to_dict(self) -> dict:
        return asdict(self)


def split_markdown(content: str) -> list[str]:
    sections = re.split(r"(?=^#{1,6}\s+)", content, flags=re.MULTILINE)
    return [s.strip() for s in sections if s.strip()]


def split_text_by_lines(content: str, max_lines: int = 80, overlap: int = 15) -> list[str]:
    lines = content.splitlines()
    chunks = []
    step = max(1, max_lines - overlap)

    for i in range(0, len(lines), step):
        block = "\n".join(lines[i:i + max_lines]).strip()
        if block:
            chunks.append(block)

    return chunks


def chunk_record(record) -> list[ChunkRecord]:
    if record.language == "markdown":
        raw_chunks = split_markdown(record.content)
    else:
        raw_chunks = split_text_by_lines(record.content)

    chunks = []

    for idx, text in enumerate(raw_chunks):
        chunks.append(
            ChunkRecord(
                chunk_id=f"{record.source_id}::chunk_{idx}",
                source_id=record.source_id,
                source_type=record.source_type,
                path=record.path,
                language=record.language,
                title=record.title,
                chunk_index=idx,
                content=text,
            )
        )

    return chunks


def chunk_all_records() -> list[ChunkRecord]:
    records = load_all_records()
    all_chunks = []

    for record in records:
        all_chunks.extend(chunk_record(record))

    return all_chunks


import json
from pathlib import Path


def save_chunks_jsonl(chunks: list[ChunkRecord], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")


if __name__ == "__main__":
    chunks = chunk_all_records()

    output_path = Path("data/processed/chunks.jsonl")
    save_chunks_jsonl(chunks, output_path)

    print(f"Created {len(chunks)} chunks")
    print(f"Saved chunks to {output_path}")

    for c in chunks[:3]:
        print("=" * 80)
        print("TITLE:", c.title)
        print("LANGUAGE:", c.language)
        print("PATH:", c.path)
        print("CHUNK INDEX:", c.chunk_index)
        print("CONTENT SAMPLE:")
        print(c.content[:500])