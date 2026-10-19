import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from backend.app import store, verified
from backend.app.db import init_db
from ingestion.config import VERIFIED_SNAPSHOT_PATH

SNAPSHOT_VERSION = 1

logger = logging.getLogger(__name__)


def export_snapshot(path: Path = VERIFIED_SNAPSHOT_PATH) -> int:
    rows = store.approved_verified_answers()
    entries = [
        {
            "question": r["question"],
            "answer": r["answer"],
            "sources": json.loads(r["sources_json"]),
            "source_hashes": json.loads(r["source_hashes_json"]),
            "origin": r["origin"],
            "reviewed_at": r["reviewed_at"],
        }
        for r in rows
    ]
    document = {
        "version": SNAPSHOT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "description": "Admin-approved Sentinel answers. Loaded automatically into an empty database at start-up; "
        "an entry whose cited files changed since approval is marked stale instead of being served.",
        "answers": entries,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    logger.info("exported %d verified answers to %s", len(entries), path)
    return len(entries)


def import_snapshot(path: Path = VERIFIED_SNAPSHOT_PATH) -> int:
    if not path.is_file():
        return 0
    document = json.loads(path.read_text(encoding="utf-8"))
    imported = 0
    for entry in document.get("answers", []):
        if store.import_verified_answer(
            entry["question"],
            entry["answer"],
            entry["sources"],
            entry.get("source_hashes", {}),
            entry.get("origin", "generated"),
            entry.get("reviewed_at"),
        ):
            imported += 1
    verified.invalidate()
    logger.info("imported %d verified answers from %s", imported, path)
    return imported


def import_if_empty(path: Path = VERIFIED_SNAPSHOT_PATH) -> int:
    if sum(store.verified_answer_counts().values()) > 0:
        return 0
    return import_snapshot(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export or import the verified-answer snapshot")
    parser.add_argument("action", choices=["export", "import"])
    parser.add_argument("--path", type=Path, default=VERIFIED_SNAPSHOT_PATH)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    init_db()
    count = export_snapshot(args.path) if args.action == "export" else import_snapshot(args.path)
    logger.info("%s: %d answers", args.action, count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
