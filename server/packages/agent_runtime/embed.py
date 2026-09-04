## file embed.py này biến câu query thành embedding rồi so sánh để lấy ra 
# các embedding trong bôj nhớ fact, working, cache giống nhất với câu query
# Rồi lấy ra text trong bộ nhớ đó để trả về cho user


from typing import List, Optional

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
        return model.embed_documents(cleaned)
    except Exception as exc:
        print(f"-> Embedding failed: {exc}")
        return [None] * len(cleaned)
