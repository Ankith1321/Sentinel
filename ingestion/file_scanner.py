from pathlib import Path

from ingestion.config import EXCLUDED_DIR_SUFFIXES, EXCLUDED_DIRS, SUPERSET_REPO, SUPPORTED_EXTENSIONS


def should_skip(path: Path, root: Path = SUPERSET_REPO) -> bool:
    parts = path.relative_to(root).parts if path.is_relative_to(root) else path.parts
    return any(part in EXCLUDED_DIRS or part.endswith(EXCLUDED_DIR_SUFFIXES) for part in parts)


def detect_language(path: Path) -> str:
    suffix = path.suffix.lower()

    mapping = {
        ".py": "python",
        ".md": "markdown",
        ".mdx": "markdown",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
    }

    return mapping.get(suffix, "text")


def scan_source_files(root: Path = SUPERSET_REPO) -> list[Path]:
    files: list[Path] = []

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        if should_skip(path, root):
            continue

        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        files.append(path)

    return files

