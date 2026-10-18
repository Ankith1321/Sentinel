import ast
import json
import logging
import re
import statistics
from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from pathlib import Path

from transformers import AutoTokenizer

from ingestion.config import (
    CHUNK_MAX_TOKENS,
    CHUNK_MIN_TOKENS,
    CHUNK_TARGET_TOKENS,
    CHUNKS_PATH,
    EMBEDDING_MODEL,
)
from ingestion.loader import load_all_records
from ingestion.records import SourceRecord

logger = logging.getLogger(__name__)

MARKDOWN_HEADING = re.compile(r"(?=^#{1,6}\s+)", flags=re.MULTILINE)
SCRIPT_BOUNDARY = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:async\s+)?"
    r"(?:function|class|const|let|var|interface|type|enum|describe|test|it)\b"
)
LICENSE_MARKER = "Licensed to the Apache Software Foundation"
LICENSE_HEADER = re.compile(
    r"\A(?:\s*(?:#[^\n]*\n|//[^\n]*\n))+"
    r"|\A\s*/\*.*?\*/"
    r"|\A\s*<!--.*?-->",
    flags=re.DOTALL,
)
MAX_SIGNATURE_TOKENS = 30
CHARS_PER_TOKEN_ESTIMATE = 3


@dataclass
class ChunkRecord:
    chunk_id: str
    source_id: str
    source_type: str
    path: str
    language: str
    title: str | None
    chunk_index: int
    content: str
    content_hash: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@lru_cache(maxsize=1)
def get_tokenizer():
    tokenizer = AutoTokenizer.from_pretrained(EMBEDDING_MODEL)
    tokenizer.model_max_length = 10**9
    return tokenizer


def count_tokens(text: str) -> int:
    return len(get_tokenizer().encode(text, add_special_tokens=False))


def count_line_tokens(lines: list[str]) -> list[int]:
    encoded = get_tokenizer()(lines, add_special_tokens=False)["input_ids"]
    return [len(ids) for ids in encoded]


def split_oversize_line(line: str, budget: int) -> list[str]:
    width = max(1, budget * CHARS_PER_TOKEN_ESTIMATE)
    return [line[i:i + width] for i in range(0, len(line), width)]


def split_by_tokens(text: str, budget: int) -> list[str]:
    lines = text.splitlines()
    signature = lines[0].strip() if lines else ""
    signature_tokens = count_tokens(signature) if signature else 0
    carry_signature = 0 < signature_tokens <= MAX_SIGNATURE_TOKENS

    pieces: list[str] = []
    current: list[str] = []
    current_tokens = 0

    def flush() -> None:
        if current:
            pieces.append("\n".join(current))
            current.clear()

    expanded: list[str] = []
    for line in lines:
        expanded.extend(split_oversize_line(line, budget) if len(line) > budget * CHARS_PER_TOKEN_ESTIMATE else [line])

    for line, tokens in zip(expanded, count_line_tokens(expanded), strict=True):
        limit = budget - (signature_tokens if carry_signature and pieces else 0)
        if current and current_tokens + tokens > limit:
            flush()
            current_tokens = 0
            if carry_signature:
                current.append(signature)
                current_tokens = signature_tokens
        current.append(line)
        current_tokens += tokens

    flush()
    return pieces


def pack_units(units: Iterable[str], budget: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for unit in units:
        if not unit.strip():
            continue

        tokens = count_tokens(unit)
        pieces = [unit] if tokens <= budget else split_by_tokens(unit, budget)

        for piece in pieces:
            piece_tokens = tokens if len(pieces) == 1 else count_tokens(piece)
            if current and current_tokens + piece_tokens > budget:
                chunks.append("\n\n".join(current))
                current, current_tokens = [], 0
            current.append(piece)
            current_tokens += piece_tokens

    if current:
        chunks.append("\n\n".join(current))

    return chunks


def definition_start(node: ast.AST) -> int:
    decorators = getattr(node, "decorator_list", [])
    return min([node.lineno] + [d.lineno for d in decorators]) - 1


def python_units(content: str, budget: int) -> list[str]:
    tree = ast.parse(content)
    lines = content.splitlines()
    units: list[str] = []
    glue_start = 0

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue

        start = definition_start(node)
        units.append("\n".join(lines[glue_start:start]))
        text = "\n".join(lines[start:node.end_lineno])

        if isinstance(node, ast.ClassDef) and count_tokens(text) > budget:
            units.extend(class_units(node, lines))
        else:
            units.append(text)

        glue_start = node.end_lineno

    units.append("\n".join(lines[glue_start:]))
    return units


def class_units(node: ast.ClassDef, lines: list[str]) -> list[str]:
    class_signature = lines[node.lineno - 1]
    members = [
        n for n in node.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]

    if not members:
        return ["\n".join(lines[definition_start(node):node.end_lineno])]

    first_member = definition_start(members[0])
    units = ["\n".join(lines[definition_start(node):first_member])]
    cursor = first_member

    for member in members:
        start = definition_start(member)
        if start > cursor:
            units.append(class_signature + "\n" + "\n".join(lines[cursor:start]))
        units.append(class_signature + "\n" + "\n".join(lines[start:member.end_lineno]))
        cursor = member.end_lineno

    if cursor < node.end_lineno:
        units.append(class_signature + "\n" + "\n".join(lines[cursor:node.end_lineno]))

    return units


def script_units(content: str) -> list[str]:
    units: list[str] = []
    current: list[str] = []

    for line in content.splitlines():
        if SCRIPT_BOUNDARY.match(line) and current:
            units.append("\n".join(current))
            current = []
        current.append(line)

    if current:
        units.append("\n".join(current))

    return units


def markdown_units(content: str) -> list[str]:
    return [section for section in MARKDOWN_HEADING.split(content) if section.strip()]


def paragraph_units(content: str) -> list[str]:
    return [p for p in re.split(r"\n\s*\n", content) if p.strip()]


def build_units(record: SourceRecord, budget: int) -> list[str]:
    if record.language == "markdown":
        return markdown_units(record.content)

    if record.language == "python":
        try:
            return python_units(record.content, budget)
        except (SyntaxError, ValueError, RecursionError):
            logger.warning("ast parse failed for %s, falling back to paragraphs", record.path)
            return paragraph_units(record.content)

    if record.language in {"javascript", "typescript"}:
        return script_units(record.content)

    return paragraph_units(record.content)


def strip_license_header(content: str) -> str:
    match = LICENSE_HEADER.match(content)

    if match and LICENSE_MARKER in match.group(0):
        return content[match.end():].lstrip("\n")

    return content


def chunk_record(record: SourceRecord) -> list[ChunkRecord]:
    record = replace(record, content=strip_license_header(record.content))
    header = f"File: {record.path}\n"
    budget = CHUNK_TARGET_TOKENS - count_tokens(header)
    bodies = pack_units(build_units(record, budget), budget)

    chunks: list[ChunkRecord] = []

    for body in bodies:
        if count_tokens(body) < CHUNK_MIN_TOKENS:
            continue

        text = header + body
        if count_tokens(text) > CHUNK_MAX_TOKENS:
            logger.warning("chunk over max tokens in %s", record.path)

        index = len(chunks)
        chunks.append(
            ChunkRecord(
                chunk_id=f"{record.source_id}::chunk_{index}",
                source_id=record.source_id,
                source_type=record.source_type,
                path=record.path,
                language=record.language,
                title=record.title,
                chunk_index=index,
                content=text,
                content_hash=record.content_hash,
            )
        )

    return chunks


def chunk_all_records() -> list[ChunkRecord]:
    all_chunks: list[ChunkRecord] = []

    for record in load_all_records():
        all_chunks.extend(chunk_record(record))

    return all_chunks


def save_chunks_jsonl(chunks: list[ChunkRecord], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    all_chunks = chunk_all_records()
    save_chunks_jsonl(all_chunks, CHUNKS_PATH)

    sizes = [count_tokens(c.content) for c in all_chunks]
    logger.info("chunks=%d saved=%s", len(all_chunks), CHUNKS_PATH)
    logger.info(
        "tokens: median=%d p95=%d max=%d over_max=%d",
        statistics.median(sizes),
        sorted(sizes)[int(len(sizes) * 0.95)],
        max(sizes),
        sum(1 for s in sizes if s > CHUNK_MAX_TOKENS),
    )
