## file embed.py này biến câu query thành embedding rồi so sánh để lấy ra
# các embedding trong bôj nhớ fact, working, cache giống nhất với câu query
# Rồi lấy ra text trong bộ nhớ đó để trả về cho user
#
# Model đọc từ GEMINI_EMBED_MODEL (mặc định `gemini-embedding-001`; `text-embedding-004`
# đã bị Google tắt ngày 14/01/2026 nên gọi vào sẽ trả 404 NOT_FOUND). Số chiều output
# đọc từ GEMINI_EMBED_DIM và phải khớp EMBEDDING_DIM của cột Vector trong DB.
#
# File này là BẢN CHUẨN của phần dùng chung (cắt text, phân loại lỗi, thử lại, gọi từng
# text khi batch lỗi). app/memory/embed.py của orchestrator import lại rồi chỉ thêm
# telemetry — nhờ vậy hai bên không trôi lệch nhau như lần hardcode model cũ.
#
# QUAN TRỌNG — quota: Gemini free tier chỉ cho 100 request/phút cho mỗi model embedding
# (lỗi 429 RESOURCE_EXHAUSTED, quotaId ...EmbedContentRequestsPerMinutePerUserPerProjectPerModel).
# Vì MỘT request đã embed được cả loạt text (tối đa 100), nguyên tắc ở đây là:
#   - gộp nhiều text vào một request thay vì gọi từng text;
#   - gặp lỗi hệ thống (429/503) thì DỪNG NGAY, không bắn thêm request — quota đã cạn thì
#     gọi thêm chỉ làm tình hình tệ hơn và ăn hết quota của cả ứng dụng đang chạy;
#   - API nói "retry in 45s" thì chờ đúng 45s (chế độ PATIENT cho script), còn đường chat
#     thì trả về None luôn để không treo câu trả lời của người dùng.


import re
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from packages.agent_runtime.models import EMBEDDING_DIM

# gemini-embedding-001 chỉ nhận 2048 token input. Ước lượng thô 3 ký tự/token (tiếng Việt
# có dấu tốn token hơn tiếng Anh) nên cắt ở 6000 ký tự. Không cắt thì API trả 400 và dòng
# đó vĩnh viễn không có embedding.
MAX_EMBED_CHARS = 6000

# Trần số request được phép bắn thêm khi phải gọi riêng từng text trong một batch lỗi.
# Không có trần này thì một batch 100 text lỗi có thể biến thành 100 request.
MAX_INDIVIDUAL_REQUESTS = 10

# Lỗi thuộc về riêng một text (quá dài, nội dung bị chặn) -> bỏ text đó rồi đi tiếp.
_ITEM_ERROR_MARKERS = ("invalid_argument", "invalid argument", "400")
# Lỗi hệ thống/tạm thời (hết quota, quá tải, mạng) -> dừng batch, chờ rồi thử lại.
_TRANSIENT_MARKERS = (
    "429",
    "resource_exhausted",
    "rate limit",
    "quota",
    "500",
    "502",
    "503",
    "504",
    "unavailable",
    "deadline",
    "timeout",
    "timed out",
    "connection",
    "temporarily",
    "overloaded",
)
# 'Please retry in 45.802764896s.' / "retryDelay': '45s'"
_RETRY_DELAY_RE = re.compile(r"retry(?:delay)?[^0-9]{0,20}(\d+(?:\.\d+)?)\s*s", re.IGNORECASE)


@dataclass(frozen=True)
class RetryPolicy:
    """Chính sách thử lại: khác nhau giữa đường chat và script chạy nền."""

    attempts: int = 2
    max_wait: float = 1.0
    individual_attempts: int = 2
    individual_max_wait: float = 1.0
    max_individual: int = MAX_INDIVIDUAL_REQUESTS


# Đường chat: người dùng đang chờ, thà mất embedding của lượt này còn hơn treo 45s.
FAST = RetryPolicy()
# Script re-embed: chờ đúng retryDelay của API rồi làm tiếp, miễn là đừng đốt quota.
PATIENT = RetryPolicy(
    attempts=5,
    max_wait=60.0,
    individual_attempts=3,
    individual_max_wait=60.0,
)

_embeddings = None


def is_item_error(message: str) -> bool:
    """Lỗi chỉ liên quan tới một text cụ thể, không phải API/khoá/model hỏng."""
    lowered = (message or "").lower()
    return any(marker in lowered for marker in _ITEM_ERROR_MARKERS)


def is_transient_error(message: str) -> bool:
    """Lỗi có thể qua đi nếu thử lại (hết quota theo phút, quá tải, mạng chập)."""
    lowered = (message or "").lower()
    return any(marker in lowered for marker in _TRANSIENT_MARKERS)


def retry_delay_seconds(message: str, default: float) -> float:
    """API thường nói sẵn phải chờ bao lâu ('Please retry in 45.8s') — chờ đúng thế."""
    match = _RETRY_DELAY_RE.search(message or "")
    if not match:
        return default
    try:
        return max(float(match.group(1)), 0.0)
    except ValueError:
        return default


def fit_to_limit(texts: List[str]) -> Tuple[List[str], int]:
    """Cắt text dài hơn MAX_EMBED_CHARS. Trả về (texts, số text bị cắt).

    Text lưu trong DB vẫn nguyên vẹn; chỉ phần đem đi embed bị cắt.
    """
    fitted = []
    truncated = 0
    for text in texts:
        if len(text) > MAX_EMBED_CHARS:
            truncated += 1
            text = text[:MAX_EMBED_CHARS]
        fitted.append(text)
    return fitted, truncated


def clean_texts(texts: List[str]) -> List[str]:
    """Bỏ text rỗng/khoảng trắng — API không nhận input rỗng."""
    return [item.strip() for item in texts if item and str(item).strip()]


def embed_with_retry(
    model,
    texts: List[str],
    attempts: int = 2,
    max_wait: float = 1.0,
) -> Tuple[Optional[List[List[float]]], Optional[str]]:
    """Gọi embed_documents, thử lại khi lỗi tạm thời. Trả về (vectors hoặc None, lỗi cuối)."""
    wait = 1.0
    for attempt in range(1, attempts + 1):
        try:
            return model.embed_documents(texts), None
        except Exception as exc:
            message = str(exc)
            if attempt == attempts or not is_transient_error(message):
                return None, message
            wait = min(retry_delay_seconds(message, wait), max_wait)
            if wait > 0:
                print(
                    f"-> Embedding lỗi tạm thời (lần {attempt}/{attempts}), "
                    f"chờ {wait:.1f}s rồi thử lại: {message[:160]}",
                    flush=True,
                )
                time.sleep(wait)
            else:
                print(
                    f"-> Embedding lỗi tạm thời (lần {attempt}/{attempts}), thử lại ngay: {message[:160]}",
                    flush=True,
                )
            wait *= 2
    return None, "unknown error"


def embed_individually(
    model,
    texts: List[str],
    policy: RetryPolicy = PATIENT,
) -> Tuple[List[Optional[List[float]]], List[Optional[str]]]:
    """Gọi riêng từng text khi cả batch lỗi, để text hỏng không kéo theo cả batch.

    Hai cái phanh bắt buộc, vì mỗi lần gọi là một request tính vào quota 100/phút:
      1. Gặp lỗi hệ thống (429/503) là dừng ngay ở bất kỳ text nào — quota đã cạn thì
         gọi thêm 50 lần nữa chỉ đốt sạch quota mà không embed được gì.
      2. Tối đa `policy.max_individual` request, phần còn lại ghi lỗi để script báo cáo.
    """
    vectors: List[Optional[List[float]]] = []
    errors: List[Optional[str]] = []
    for index, text in enumerate(texts):
        if index >= policy.max_individual:
            reason = f"dừng sau {policy.max_individual} request riêng để tiết kiệm quota"
            vectors.extend([None] * (len(texts) - index))
            errors.extend([reason] * (len(texts) - index))
            break
        single, error = embed_with_retry(
            model,
            [text],
            attempts=policy.individual_attempts,
            max_wait=policy.individual_max_wait,
        )
        if single is not None:
            vectors.append(single[0])
            errors.append(None)
            continue
        print(f"-> Embedding failed for one text: {error}", flush=True)
        if not is_item_error(error):
            reason = error or "lỗi hệ thống"
            vectors.extend([None] * (len(texts) - index))
            errors.extend([reason] * (len(texts) - index))
            break
        vectors.append(None)
        errors.append(error or "embedding failed")
    return vectors, errors


def accept_dimension(vector, model_name: str = "") -> Optional[List[float]]:
    """Chặn vector sai số chiều trước khi SQLAlchemy ghi vào cột Vector(EMBEDDING_DIM)."""
    if vector is None:
        return None  # đã log lỗi ở trên rồi
    values = list(vector)
    if len(values) != EMBEDDING_DIM:
        print(
            f"-> Embedding dimension mismatch: {model_name or 'model'} trả {len(values)} chiều, "
            f"cột DB cần {EMBEDDING_DIM}. Kiểm tra GEMINI_EMBED_DIM khớp EMBEDDING_DIM."
        )
        return None
    return values


def embed_texts_detailed(
    model,
    texts: List[str],
    model_name: str = "",
    on_done: Optional[Callable[[List[str], float, List[Optional[str]]], None]] = None,
    policy: RetryPolicy = FAST,
) -> Tuple[List[Optional[List[float]]], List[Optional[str]]]:
    """Embed một loạt text, trả về (vectors, errors) cùng độ dài với `texts` đã lọc rỗng.

    errors[i] là lý do text i thất bại (None nếu thành công) — cần cho báo cáo của
    scripts/reembed_memory.py, thay vì chỉ in ra stdout rồi mất.
    on_done(texts, duration_ms, errors) được gọi một lần để bên gọi ghi telemetry.
    """
    cleaned = clean_texts(texts)
    if not cleaned:
        return [], []

    prepared, truncated = fit_to_limit(cleaned)
    if truncated:
        print(
            f"-> Đã cắt {truncated}/{len(prepared)} text dài hơn {MAX_EMBED_CHARS} ký tự "
            f"trước khi embed (text trong DB giữ nguyên)",
            flush=True,
        )

    started = time.perf_counter()
    vectors, error = embed_with_retry(model, prepared, attempts=policy.attempts, max_wait=policy.max_wait)
    if vectors is not None:
        errors: List[Optional[str]] = [None] * len(prepared)
    else:
        print(f"-> Embedding failed: {error}", flush=True)
        if len(prepared) > 1:
            vectors, errors = embed_individually(model, prepared, policy=policy)
        else:
            # Batch chỉ có 1 text thì gọi riêng cũng là chính request đó, không cần thử lại.
            vectors = [None]
            errors = [error or "embedding failed"]
    elapsed_ms = (time.perf_counter() - started) * 1000

    results: List[Optional[List[float]]] = []
    for index, vector in enumerate(vectors):
        accepted = accept_dimension(vector, model_name)
        if accepted is None:
            errors[index] = errors[index] or "sai số chiều"
        results.append(accepted)

    if on_done is not None:
        on_done(prepared, elapsed_ms, errors)
    return results, errors


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
        model_name = embed_model_name()
        embed_dim = int(os.getenv("GEMINI_EMBED_DIM", str(EMBEDDING_DIM)))
        if embed_dim != EMBEDDING_DIM:
            print(
                f"-> Embeddings unavailable: GEMINI_EMBED_DIM={embed_dim} nhưng cột DB cần "
                f"{EMBEDDING_DIM} chiều. Sửa env cho khớp packages/agent_runtime/models.py."
            )
            _embeddings = False
            return None
        _embeddings = GoogleGenerativeAIEmbeddings(
            model=model_name,
            google_api_key=api_key,
            output_dimensionality=embed_dim,
        )
        if getattr(_embeddings, "output_dimensionality", None) != embed_dim:
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


def embed_model_name() -> str:
    """Ten model embedding dang dung.

    Ghi gia tri nay vao cot `embed_model` cua memory de biet mot vector duoc sinh boi
    model nao: tron vector cua hai model khac nhau thi cosine vo nghia (xem
    server/scripts/reembed_memory.py).
    """
    import os

    return os.getenv("GEMINI_EMBED_MODEL", "models/gemini-embedding-001")


def embed_texts(texts: List[str], policy: RetryPolicy = FAST) -> List[Optional[List[float]]]:
    model = _get_embeddings()
    if model is None:
        return [None] * len(clean_texts(texts))
    vectors, _ = embed_texts_detailed(model, texts, policy=policy)
    return vectors


def embed_text(text: str) -> Optional[List[float]]:
    vectors = embed_texts([text])
    return vectors[0] if vectors else None
