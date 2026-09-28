import chromadb
from sentence_transformers import SentenceTransformer


CHROMA_PATH = "data/indexes/chroma"
COLLECTION_NAME = "superset_codebase"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

_model = None


def get_model() -> SentenceTransformer:
    global _model

    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL)

    return _model


def get_collection():
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    return client.get_collection(name=COLLECTION_NAME)


def retrieve(query: str, top_k: int = 5):
    model = get_model()
    collection = get_collection()

    query_embedding = model.encode(
        [query],
        normalize_embeddings=True,
    )[0].tolist()

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    output = []

    for i in range(len(results["ids"][0])):
        output.append(
            {
                "id": results["ids"][0][i],
                "content": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i],
            }
        )

    return output


if __name__ == "__main__":
    query = input("Ask about Apache Superset: ")

    matches = retrieve(query, top_k=5)

    for i, match in enumerate(matches, start=1):
        print("=" * 100)
        print(f"RESULT {i}")
        print("DISTANCE:", match["distance"])
        print("PATH:", match["metadata"]["path"])
        print("LANGUAGE:", match["metadata"]["language"])
        print("TITLE:", match["metadata"]["title"])
        print("CONTENT SAMPLE:")
        print(match["content"][:1200])