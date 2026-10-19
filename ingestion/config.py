import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]

load_dotenv(PROJECT_ROOT / ".env")

SUPERSET_REPO = PROJECT_ROOT / "workspace" / "superset"

DEFAULT_COLLECTION = "superset_codebase"
COLLECTION_NAME = os.getenv("SENTINEL_COLLECTION", DEFAULT_COLLECTION)

CHROMA_PATH = str(PROJECT_ROOT / "data" / "indexes" / "chroma")
DB_PATH = Path(os.getenv("SENTINEL_DB_PATH", PROJECT_ROOT / "data" / "sentinel.db"))
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
CHUNKS_PATH = PROCESSED_DIR / (
    "chunks.jsonl" if COLLECTION_NAME == DEFAULT_COLLECTION else f"chunks_{COLLECTION_NAME}.jsonl"
)

EMBEDDING_MODEL = os.getenv("SENTINEL_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")

QUERY_PREFIX = os.getenv("SENTINEL_QUERY_PREFIX", "")
# The definition list is fused as a third ranking with extra weight: when a question names a symbol,
# the chunk that defines it should beat the many chunks that merely use it.
SYMBOL_WEIGHT = float(os.getenv("SENTINEL_SYMBOL_WEIGHT", "3.0"))
TEST_PATH_PENALTY = float(os.getenv("SENTINEL_TEST_PATH_PENALTY", "0.6"))
LOG_LEVEL = os.getenv("SENTINEL_LOG_LEVEL", "INFO")
RERANK_MODEL = os.getenv("SENTINEL_RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
RETRIEVAL_MODE = os.getenv("SENTINEL_RETRIEVAL_MODE", "hybrid")

# The embedder silently truncates input past its window, so chunks must fit inside it or their
# tails are never searchable. bge-small has a 512-token window, but 200-token chunks scored best
# (hybrid MRR 0.506 vs 0.453 at 400); MiniLM, with its 256-token window, needs <= 240 anyway.
CHUNK_TARGET_TOKENS = int(os.getenv("SENTINEL_CHUNK_TARGET_TOKENS", "200"))
CHUNK_MAX_TOKENS = int(os.getenv("SENTINEL_CHUNK_MAX_TOKENS", "240"))
CHUNK_MIN_TOKENS = 20

CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("SENTINEL_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
    if origin.strip()
]
UPLOAD_PATH_PREFIX ="uploads/"
MAX_UPLOAD_BYTES = int(os.getenv("SENTINEL_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))

LLM_PROVIDER =os.getenv("SENTINEL_LLM_PROVIDER", "auto")
ANTHROPIC_MODEL = os.getenv("SENTINEL_ANTHROPIC_MODEL", "claude-haiku-5-5")
# On the answer eval the 7B (4-bit) and 3B tied with the strict prompt, and the 1.5B cited a source in
# only 5% of answers. 7B is the default because it is Apache-2.0; Qwen2.5-3B is licensed for
# non-commercial use only. 4-bit keeps it inside an 8 GB GPU.
LOCAL_LLM_MODEL = os.getenv("SENTINEL_LOCAL_LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct")
LOCAL_LLM_QUANT = os.getenv("SENTINEL_LOCAL_LLM_QUANT", "4bit")
PROMPT_VARIANT = os.getenv("SENTINEL_PROMPT_VARIANT", "v2")
MAX_ANSWER_TOKENS = int(os.getenv("SENTINEL_MAX_ANSWER_TOKENS", "600"))
CONTEXT_TOKEN_BUDGET = int(os.getenv("SENTINEL_CONTEXT_TOKEN_BUDGET", "4000"))

SUPPORTED_EXTENSIONS = {
    ".py",
    ".md",
    ".mdx",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
}

EXCLUDED_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    ".next",
    "coverage",
}

# Docusaurus keeps an archived copy of the docs for every past release. These near-duplicates
# filled 24% of all top-5 results after the October 2026 pull and pushed current docs out.
EXCLUDED_DIR_SUFFIXES = ("_versioned_docs", "_versioned_sidebars")
