import json
import logging
from collections.abc import Iterator

import chromadb
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

from ingestion.config import CHROMA_PATH, CHUNKS_PATH, COLLECTION_NAME, EMBEDDING_MODEL

BATCH_SIZE = 64
ID_PAGE_SIZE = 5000

logger = logging.getLogger(__name__)


def load_chunks() -> Iterator[dict]:
    with CHUNKS_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def delete_stale_chunks(collection, keep_ids: set[str]) -> int:
    stale: list[str] = []

    for offset in range(0, collection.count(), ID_PAGE_SIZE):
        page = collection.get(limit=ID_PAGE_SIZE, offset=offset, include=[])
        stale.extend(i for i in page["ids"] if i not in keep_ids)

    for start in range(0, len(stale), ID_PAGE_SIZE):
        collection.delete(ids=stale[start:start + ID_PAGE_SIZE])

    return len(stale)


def main() -> None:
    if not CHUNKS_PATH.exists():
        raise FileNotFoundError(f"Missing {CHUNKS_PATH}. Run the chunker first.")

    logger.info("embedding model: %s", EMBEDDING_MODEL)
    model = SentenceTransformer(EMBEDDING_MODEL)

    client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine", "description": "Apache Superset code/docs chunks"},
    )

    chunks = list(load_chunks())
    logger.info("loaded %d chunks into collection %s", len(chunks), COLLECTION_NAME)

    for start in tqdm(range(0, len(chunks), BATCH_SIZE), desc="Embedding chunks"):
        batch = chunks[start:start + BATCH_SIZE]
        texts = [c["content"] for c in batch]

        embeddings = model.encode(
            texts,
            batch_size=BATCH_SIZE,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).tolist()

        collection.upsert(
            ids=[c["chunk_id"] for c in batch],
            documents=texts,
            embeddings=embeddings,
            metadatas=[
                {
                    "source_id": c["source_id"],
                    "source_type": c["source_type"],
                    "path": c["path"],
                    "language": c["language"],
                    "title": c["title"] or "",
                    "chunk_index": c["chunk_index"],
                }
                for c in batch
            ],
        )

    removed = delete_stale_chunks(collection, {c["chunk_id"] for c in chunks})
    logger.info("removed %d stale chunks; collection count=%d", removed, collection.count())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
