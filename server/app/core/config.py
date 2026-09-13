"""Nơi duy nhất đọc biến môi trường.

Mọi module khác import hằng số từ đây thay vì gọi os.getenv rải rác, để biết
được toàn bộ cấu hình mà dịch vụ cần chỉ bằng cách đọc một file.
"""
import os

from dotenv import load_dotenv

load_dotenv()


def _flag(name: str, default: str = "False") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


# --- LLM ---------------------------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
OPENAI_REASONING_EFFORT = os.getenv("OPENAI_REASONING_EFFORT", "low")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# --- Cơ sở dữ liệu -----------------------------------------------------------
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://travel:travel@localhost:5432/travel_agent",
)

# --- Xác thực ----------------------------------------------------------------
JWT_SECRET = os.getenv("JWT_SECRET", "dev-change-me")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "72"))

# --- Địa chỉ các microservice ------------------------------------------------
FLIGHT_SERVICE_URL = os.getenv("FLIGHT_SERVICE_URL", "http://flight-service:8000")
HOTEL_SERVICE_URL = os.getenv("HOTEL_SERVICE_URL", "http://hotel-service:8001")
ACTIVITY_SERVICE_URL = os.getenv("ACTIVITY_SERVICE_URL", "http://activity-service:8002")
GEOCODING_SERVICE_URL = os.getenv("GEOCODING_SERVICE_URL", "http://geocoding-service:8003")
EVENT_SERVICE_URL = os.getenv("EVENT_SERVICE_URL", "http://event-service:8004")

# --- Chạy thử / xuất file ----------------------------------------------------
MOCK_MODE = _flag("MOCK_MODE")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")
