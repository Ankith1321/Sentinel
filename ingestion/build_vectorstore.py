import json
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer
from tqdm import tqdm


CHUNKS_PATH = Path("data/processed/chunks.jsonl")
CHROMA_PATH = "data/indexes/chroma"
COLLECTION_NAME = "superset_codebase"

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
BATCH_SIZE = 64


def load_chunks():
    with CHUNKS_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def main():
    if not CHUNKS_PATH.exists():
        raise FileNotFoundError(f"Missing {CHUNKS_PATH}. Run chunker first.")

    print("Loading embedding model...")
    model = SentenceTransformer(EMBEDDING_MODEL)

    print("Connecting to ChromaDB...")
    client = chromadb.PersistentClient(path=CHROMA_PATH)

    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"description": "Apache Superset code/docs chunks"},
    )

    chunks = list(load_chunks())
    print(f"Loaded {len(chunks)} chunks")

    for start in tqdm(range(0, len(chunks), BATCH_SIZE), desc="Embedding chunks"):
        batch = chunks[start:start + BATCH_SIZE]

        texts = [c["content"] for c in batch]
        ids = [c["chunk_id"] for c in batch]

        embeddings = model.encode(
            texts,
            batch_size=BATCH_SIZE,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).tolist()

        metadatas = [
            {
                "source_id": c["source_id"],
                "source_type": c["source_type"],
                "path": c["path"],
                "language": c["language"],
                "title": c["title"] or "",
                "chunk_index": c["chunk_index"],
            }
            for c in batch
        ]

        collection.upsert(
            ids=ids,
            documents=texts,
            embeddings=embeddings,
            metadatas=metadatas,
        )

    print("Vectorstore build complete.")
    print(f"Collection count: {collection.count()}")
    print(f"Saved to: {CHROMA_PATH}")


if __name__ == "__main__":
    main()