"""Cấu hình chung cho test: đặt server/ lên sys.path và nạp env giả.

Test ở đây là smoke test cấu trúc — không gọi LLM, không cần Postgres.
"""
import os
import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

# app/core/llm.py dừng chương trình nếu thiếu khoá; test không gọi API thật.
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("GEMINI_API_KEY", "test-key")
