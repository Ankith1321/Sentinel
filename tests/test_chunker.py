import ast

from ingestion.chunker import (
    chunk_record,
    count_tokens,
    pack_units,
    python_units,
    split_by_tokens,
    strip_license_header,
)
from ingestion.loader import stable_source_id
from ingestion.records import SourceRecord

SMALL_MODULE = '''import os


def load_settings(path):
    """Read settings from disk and return them as a dict."""
    with open(path) as handle:
        return {"raw": handle.read(), "dir": os.path.dirname(path)}


class Repository:
    def get(self, key):
        return self.cache.get(key)

    def put(self, key, value):
        self.cache[key] = value
'''


def make_record(content: str, language: str = "python") -> SourceRecord:
    return SourceRecord(
        source_id=stable_source_id("pkg/mod.py"),
        source_type="code",
        path="pkg/mod.py",
        language=language,
        title="mod.py",
        content=content,
    )


def test_python_units_keep_each_function_whole():
    units = python_units(SMALL_MODULE, budget=1000)

    function_unit = next(u for u in units if u.startswith("def load_settings"))
    ast.parse(function_unit)
    assert "return {" in function_unit


def test_large_class_is_split_per_method_with_class_signature():
    units = python_units(SMALL_MODULE, budget=10)

    method_units = [u for u in units if "def get" in u or "def put" in u]
    assert len(method_units) == 2
    assert all(u.startswith("class Repository:") for u in method_units)


def test_pack_units_never_exceeds_budget():
    units = [f"def f{i}(x):\n    return x + {i}" for i in range(60)]

    chunks = pack_units(units, budget=60)

    assert len(chunks) > 1
    assert all(count_tokens(c) <= 60 for c in chunks)
    assert "".join(chunks).count("def f") == 60


def test_oversize_function_continuation_repeats_signature():
    body = "\n".join(f"    value_{i} = compute({i}) + other_{i}" for i in range(80))
    function = f"def build_report(options):\n{body}"

    pieces = split_by_tokens(function, budget=60)

    assert len(pieces) > 2
    assert all(count_tokens(p) <= 60 for p in pieces)
    assert all(p.startswith("def build_report(options):") for p in pieces)


def test_license_header_is_stripped_only_when_present():
    licensed = "# Licensed to the Apache Software Foundation (ASF) under one\n# or more.\nimport os\n"
    plain = "# helper notes\nimport os\n"

    assert strip_license_header(licensed) == "import os\n"
    assert strip_license_header(plain) == plain


def test_block_comment_license_is_stripped_from_typescript():
    licensed = "/**\n * Licensed to the Apache Software Foundation (ASF)\n */\nexport const a = 1;\n"

    assert strip_license_header(licensed) == "export const a = 1;\n"


def test_noise_chunks_below_minimum_tokens_are_dropped():
    assert chunk_record(make_record("x = 1\n")) == []


def test_chunk_ids_are_stable_across_runs():
    first = chunk_record(make_record(SMALL_MODULE))
    second = chunk_record(make_record(SMALL_MODULE))

    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]
    assert all(c.content.startswith("File: pkg/mod.py\n") for c in first)


def test_source_id_depends_only_on_path():
    assert stable_source_id("a/b.py") == stable_source_id("a/b.py")
    assert stable_source_id("a/b.py") != stable_source_id("a/c.py")
