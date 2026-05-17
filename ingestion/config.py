from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SUPERSET_REPO = PROJECT_ROOT / "workspace" / "superset"

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