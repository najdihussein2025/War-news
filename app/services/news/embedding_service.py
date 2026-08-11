from sentence_transformers import SentenceTransformer

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"

_model = SentenceTransformer(EMBEDDING_MODEL_NAME)


def generate_embedding(text: str) -> list[float]:
    embedding = _model.encode(text, normalize_embeddings=True)
    return embedding.tolist()
