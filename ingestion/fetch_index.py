import argparse
import logging
import os
import sys
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download

from ingestion.config import CHROMA_PATH

INDEX_REPO = os.getenv("SENTINEL_INDEX_REPO", "")

logger = logging.getLogger(__name__)


def index_present(path: str = CHROMA_PATH) -> bool:
    return (Path(path) / "chroma.sqlite3").exists()


def fetch_index(repo_id: str = INDEX_REPO, target: str = CHROMA_PATH) -> bool:
    if index_present(target):
        logger.info("index already at %s, nothing to download", target)
        return False

    if not repo_id:
        raise SystemExit(f"No index at {target} and SENTINEL_INDEX_REPO is not set")

    logger.info("downloading the index from %s to %s", repo_id, target)
    snapshot_download(repo_id=repo_id, repo_type="dataset", local_dir=target)
    return True


def publish_index(repo_id: str, source: str = CHROMA_PATH) -> None:
    if not index_present(source):
        raise SystemExit(f"No index at {source} to publish")

    api = HfApi()
    api.create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True)
    api.upload_folder(repo_id=repo_id, repo_type="dataset", folder_path=source)
    logger.info("published %s to %s", source, repo_id)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download the vector index from a Hugging Face dataset when it is missing, or publish it. "
        "Stop the API before publishing so the files are consistent."
    )
    parser.add_argument("--publish", metavar="REPO_ID", help="upload the local index to this dataset repo")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    if args.publish:
        publish_index(args.publish)
    else:
        fetch_index()
    return 0


if __name__ == "__main__":
    sys.exit(main())
