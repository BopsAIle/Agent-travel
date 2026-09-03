import time
from typing import List, Optional

from telemetry import record_embed

_embeddings = None


def _get_embeddings():
    global _embeddings
    if _embeddings is False:
        return None
    if _embeddings is not None:
        return _embeddings
    try:
        import os

        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            _embeddings = False
            return None
        _embeddings = GoogleGenerativeAIEmbeddings(
            model="models/text-embedding-004",
            google_api_key=api_key,
        )
        return _embeddings
    except Exception as exc:
        print(f"-> Embeddings unavailable: {exc}")
        _embeddings = False
        return None


def embed_text(text: str) -> Optional[List[float]]:
    vectors = embed_texts([text])
    return vectors[0] if vectors else None


def embed_texts(texts: List[str]) -> List[Optional[List[float]]]:
    cleaned = [item.strip() for item in texts if item and str(item).strip()]
    if not cleaned:
        return []
    model = _get_embeddings()
    if model is None:
        return [None] * len(cleaned)
    try:
        t0 = time.perf_counter()
        vectors = model.embed_documents(cleaned)
        record_embed(cleaned, (time.perf_counter() - t0) * 1000)
        return vectors
    except Exception as exc:
        print(f"-> Embedding failed: {exc}")
        record_embed(cleaned, 0, status="error", error=str(exc)[:500])
        return [None] * len(cleaned)
