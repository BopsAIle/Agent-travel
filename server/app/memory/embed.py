"""Biến text thành embedding để memory so sánh theo ngữ nghĩa.

Model đọc từ GEMINI_EMBED_MODEL (mặc định `gemini-embedding-001`; `text-embedding-004`
đã bị Google tắt ngày 14/01/2026 nên gọi vào sẽ trả 404 NOT_FOUND), số chiều output đọc
từ GEMINI_EMBED_DIM và phải khớp EMBEDDING_DIM của cột Vector trong DB.

Phần lõi (cắt text quá dài, phân loại lỗi, thử lại, gọi từng text khi batch lỗi) nằm ở
packages/agent_runtime/embed.py để bản orchestrator và bản agent-service không trôi lệch
nhau. File này chỉ thêm telemetry.
"""

from typing import List, Optional, Tuple

from app.core.config import GEMINI_API_KEY, GEMINI_EMBED_DIM, GEMINI_EMBED_MODEL
from app.core.telemetry import record_embed
from app.db.models import EMBEDDING_DIM
from packages.agent_runtime.embed import FAST, RetryPolicy, clean_texts, embed_texts_detailed

_embeddings = None


def _get_embeddings():
    global _embeddings
    if _embeddings is False:
        return None
    if _embeddings is not None:
        return _embeddings
    if GEMINI_EMBED_DIM != EMBEDDING_DIM:
        print(
            f"-> Embeddings unavailable: GEMINI_EMBED_DIM={GEMINI_EMBED_DIM} nhưng cột DB "
            f"cần {EMBEDDING_DIM} chiều. Sửa env cho khớp EMBEDDING_DIM trong app/db/models.py."
        )
        _embeddings = False
        return None
    try:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        api_key = GEMINI_API_KEY
        if not api_key:
            _embeddings = False
            return None
        _embeddings = GoogleGenerativeAIEmbeddings(
            model=GEMINI_EMBED_MODEL,
            google_api_key=api_key,
            output_dimensionality=GEMINI_EMBED_DIM,
        )
        if getattr(_embeddings, "output_dimensionality", None) != GEMINI_EMBED_DIM:
            # Bản langchain-google-genai cũ bỏ qua tham số này, model sẽ trả 3072 chiều
            # và không insert được vào cột 768 chiều — dừng sớm còn hơn hỏng âm thầm.
            print(
                "-> Embeddings unavailable: langchain-google-genai không hỗ trợ "
                "output_dimensionality. Cập nhật thư viện rồi build lại image."
            )
            _embeddings = False
            return None
        return _embeddings
    except Exception as exc:
        print(f"-> Embeddings unavailable: {exc}")
        _embeddings = False
        return None


def embed_text(text: str) -> Optional[List[float]]:
    vectors = embed_texts([text])
    return vectors[0] if vectors else None


def embed_texts(texts: List[str]) -> List[Optional[List[float]]]:
    vectors, _ = embed_texts_with_errors(texts)
    return vectors


def embed_texts_with_errors(
    texts: List[str],
    model=None,
    record: bool = True,
    policy: RetryPolicy = FAST,
) -> Tuple[List[Optional[List[float]]], List[Optional[str]]]:
    """Như embed_texts nhưng trả thêm lý do lỗi từng text (dùng cho script re-embed).

    `policy` mặc định là FAST (đường chat: không chờ lâu). Script re-embed truyền PATIENT
    để chờ đúng retryDelay của API thay vì bỏ dở.
    """
    model = model or _get_embeddings()
    if model is None:
        cleaned = clean_texts(texts)
        return [None] * len(cleaned), ["embeddings unavailable"] * len(cleaned)

    on_done = None
    if record:

        def record_span(prepared: List[str], elapsed_ms: float, errors: List[Optional[str]]) -> None:
            failed = sum(1 for item in errors if item)
            if failed:
                reasons = sorted({item for item in errors if item})
                record_embed(
                    prepared,
                    elapsed_ms,
                    status="error",
                    error=f"{failed}/{len(errors)} texts failed: {'; '.join(reasons)}"[:500],
                )
            else:
                record_embed(prepared, elapsed_ms)

        on_done = record_span

    return embed_texts_detailed(
        model,
        texts,
        model_name=GEMINI_EMBED_MODEL,
        on_done=on_done,
        policy=policy,
    )
