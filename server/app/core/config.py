"""Nơi duy nhất đọc biến môi trường.

Mọi module khác import hằng số từ đây thay vì gọi os.getenv rải rác, để biết
được toàn bộ cấu hình mà dịch vụ cần chỉ bằng cách đọc một file.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# load_dotenv() không tham số tìm .env theo cwd, nên chạy script từ thư mục khác
# (ví dụ `python server/scripts/reembed_memory.py` ở gốc repo) sẽ không nạp được file.
# Trỏ thẳng vào server/.env; biến môi trường thật của Docker vẫn được ưu tiên vì
# load_dotenv mặc định không override.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def _flag(name: str, default: str = "False") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


# --- LLM ---------------------------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
OPENAI_REASONING_EFFORT = os.getenv("OPENAI_REASONING_EFFORT", "low")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# --- Embedding (memory) ------------------------------------------------------
# text-embedding-004 đã bị Google tắt ngày 14/01/2026 nên không dùng được nữa.
# gemini-embedding-001 là model text GA, còn hỗ trợ tới 14/05/2028.
GEMINI_EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "models/gemini-embedding-001")
# PHẢI khớp EMBEDDING_DIM trong app/db/models.py, nếu không vector không insert
# được vào cột Vector(EMBEDDING_DIM). Model mới mặc định 3072 chiều nên phải ép
# xuống 768 bằng output_dimensionality (MRL, hỗ trợ 128-3072).
GEMINI_EMBED_DIM = int(os.getenv("GEMINI_EMBED_DIM", "768"))

# --- Cơ sở dữ liệu -----------------------------------------------------------
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://travel:travel@localhost:5432/travel_agent",
)

# --- Xác thực ----------------------------------------------------------------
# Khoá mặc định cho dev, CỐ TÌNH dài >= 32 byte để không còn cảnh báo
# InsecureKeyLengthWarning của PyJWT. Chạy thật thì đặt JWT_SECRET trong server/.env.
DEV_JWT_SECRET = "dev-only-secret-change-me-at-least-32-bytes-long"
JWT_SECRET = (os.getenv("JWT_SECRET") or "").strip() or DEV_JWT_SECRET
JWT_SECRET_IS_DEV_DEFAULT = JWT_SECRET == DEV_JWT_SECRET
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "72"))

# --- Địa chỉ các microservice ------------------------------------------------
FLIGHT_SERVICE_URL = os.getenv("FLIGHT_SERVICE_URL", "http://flight-service:8000")
HOTEL_SERVICE_URL = os.getenv("HOTEL_SERVICE_URL", "http://hotel-service:8001")
ACTIVITY_SERVICE_URL = os.getenv("ACTIVITY_SERVICE_URL", "http://activity-service:8002")
GEOCODING_SERVICE_URL = os.getenv("GEOCODING_SERVICE_URL", "http://geocoding-service:8003")
EVENT_SERVICE_URL = os.getenv("EVENT_SERVICE_URL", "http://event-service:8004")

# --- Ngân sách thời gian cho geocoding ---------------------------------------
# Nominatim chậm, hoặc không resolve được vì DNS, làm geopy retry rất lâu (đã đo:
# một lượt mất ~7 phút). Node geocoding phải bỏ cuộc sớm thay vì giữ request của
# người dùng lâu như các agent khác.
GEOCODING_AGENT_TIMEOUT = float(os.getenv("GEOCODING_AGENT_TIMEOUT", "20"))
GEOCODING_FALLBACK_BUDGET = float(os.getenv("GEOCODING_FALLBACK_BUDGET", "10"))

# --- Tỷ giá quy đổi ngân sách ------------------------------------------------
# Số đơn vị ngoại tệ cho 1 EUR. Dùng để so ngân sách người dùng nói (VND, USD...)
# với giá của nhà cung cấp, vì Booking.com luôn trả EUR. Trước đây hai con số này bị
# so trực tiếp nên ngân sách 30.000.000 VND luôn được coi là "trong ngân sách".
# Tỷ giá tham khảo, cập nhật tay khi lệch nhiều — không gọi mạng lúc chạy.
FX_UNITS_PER_EUR = {
    "EUR": 1.0,
    "USD": 1.09,
    "VND": 28500.0,
    "KRW": 1500.0,
    "JPY": 170.0,
    "GBP": 0.85,
    "SGD": 1.45,
    "THB": 38.0,
    "CNY": 7.9,
    "HKD": 8.5,
    "TWD": 35.0,
    "MYR": 5.1,
    "AUD": 1.65,
    "INR": 92.0,
    "IDR": 17500.0,
    "PHP": 62.0,
}

# --- Chạy thử / xuất file ----------------------------------------------------
MOCK_MODE = _flag("MOCK_MODE")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")
