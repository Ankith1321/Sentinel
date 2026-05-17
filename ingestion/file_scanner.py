from pathlib import Path

from ingestion.config import SUPERSET_REPO, SUPPORTED_EXTENSIONS, EXCLUDED_DIRS


def should_skip(path: Path) -> bool:
    return any(part in EXCLUDED_DIRS for part in path.parts)


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

        if should_skip(path):
            continue

        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        files.append(path)

    return files


if __name__ == "__main__":
    files = scan_source_files()
    print(f"Found {len(files)} source files")

    for f in files[:20]:
        print(f.relative_to(SUPERSET_REPO))