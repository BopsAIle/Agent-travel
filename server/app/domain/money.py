"""Quy đổi tiền tệ cho ngân sách chuyến đi — thuần tuý, không gọi mạng.

Vấn đề gốc: `TripRequest.budget` lấy nguyên con số người dùng nói (ví dụ
30.000.000) nhưng `evaluator` so nó với tổng chi phí tính bằng EUR, vì Booking.com
luôn trả EUR (`currency_code: "EUR"`). `514.13 > 30_000_000` là sai, nên **mọi** kế
hoạch đều được báo "Within Budget", và report in ra "€30000000".

Từ đây: `budget` luôn là EUR; số người dùng nói giữ nguyên ở `budget_original` +
`budget_currency`. Không rõ tiền tệ thì giữ nguyên số cũ (coi như EUR) để không đổi
hành vi của các chuyến trước.

Module này không import DB/LLM nên test offline được.
"""

from __future__ import annotations

import re
from typing import Optional

from app.core.config import FX_UNITS_PER_EUR

# Dấu hiệu nhận biết tiền tệ. Khoá đã ở dạng chữ thường, không dấu khi cần.
_CURRENCY_WORDS = {
    "vnd": "VND", "vnđ": "VND", "đ": "VND", "₫": "VND", "đồng": "VND",
    "usd": "USD", "$": "USD", "đô": "USD", "đô la": "USD", "dollar": "USD",
    "eur": "EUR", "€": "EUR", "euro": "EUR",
    "krw": "KRW", "₩": "KRW", "won": "KRW",
    "jpy": "JPY", "¥": "JPY", "yen": "JPY",
    "gbp": "GBP", "£": "GBP", "pound": "GBP",
    "sgd": "SGD", "thb": "THB", "baht": "THB",
    "cny": "CNY", "rmb": "CNY", "yuan": "CNY",
    "hkd": "HKD", "twd": "TWD", "myr": "MYR", "ringgit": "MYR",
    "aud": "AUD", "inr": "INR", "rupee": "INR", "idr": "IDR", "php": "PHP",
}

# Mã ISO thì không thể lẫn với từ thường, nên nhận cả khi không có số đi kèm.
_ISO_CODES = ("vnd", "usd", "eur", "krw", "jpy", "gbp", "sgd", "thb", "cny",
              "hkd", "twd", "myr", "aud", "inr", "idr", "php")

_MARKERS_BY_LENGTH = "|".join(
    re.escape(marker) for marker in sorted(_CURRENCY_WORDS, key=len, reverse=True)
)
_NUMBER = r"\d[\d.,]*"
# "30.000.000 VND", "1.500.000đ", "2000 won"
_AFTER_NUMBER = re.compile(
    rf"{_NUMBER}\s*({_MARKERS_BY_LENGTH})(?![a-zà-ỹ])", re.IGNORECASE
)
# "$1500", "€500", "₫200000"
_BEFORE_NUMBER = re.compile(rf"([$€₫₩£¥])\s*{_NUMBER}")

_AMOUNT = re.compile(
    r"(\d[\d.,]*)\s*(triệu|trieu|tr|million|nghìn|nghin|ngàn|ngan|thousand|k)?",
    re.IGNORECASE,
)
_UNIT_MULTIPLIER = {
    "triệu": 1e6, "trieu": 1e6, "tr": 1e6, "million": 1e6,
    "nghìn": 1e3, "nghin": 1e3, "ngàn": 1e3, "ngan": 1e3, "thousand": 1e3, "k": 1e3,
}


def _fold(text: str) -> str:
    import unicodedata

    normalized = unicodedata.normalize("NFD", text or "")
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn").casefold()


def _groups_are_thousands(text: str, separator: str) -> bool:
    parts = text.split(separator)
    if len(parts) < 2:
        return False
    if any(len(part) != 3 for part in parts[1:]):
        return False
    return len(parts[0]) <= 3


def _to_float(raw: str) -> Optional[float]:
    text = (raw or "").strip().rstrip(".,")
    if not text:
        return None
    if "," in text and "." in text:
        # Dấu xuất hiện sau cùng là dấu thập phân.
        text = (
            text.replace(".", "").replace(",", ".")
            if text.rfind(",") > text.rfind(".")
            else text.replace(",", "")
        )
    elif "," in text:
        text = text.replace(",", "") if _groups_are_thousands(text, ",") else text.replace(",", ".")
    elif "." in text and _groups_are_thousands(text, "."):
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def parse_amount(text: str) -> Optional[float]:
    """Đọc số tiền kiểu Việt/Anh: '30.000.000', '1,500', '2 triệu', '500k', '1.5tr'."""
    match = _AMOUNT.search(text or "")
    if not match:
        return None
    value = _to_float(match.group(1))
    if value is None:
        return None
    unit = (match.group(2) or "").casefold()
    return value * _UNIT_MULTIPLIER.get(unit, 1.0)


def detect_currency(text: str) -> Optional[str]:
    """Tìm tiền tệ trong câu người dùng.

    Ưu tiên dấu hiệu **đi kèm một con số** ("30.000.000 VND", "$1500") để không nhầm
    "đồng ý" thành tiền đồng. Chỉ khi không có số đi kèm mới nhận mã ISO rõ ràng.
    """
    if not text:
        return None
    match = _AFTER_NUMBER.search(text)
    if match:
        return _CURRENCY_WORDS[match.group(1).casefold()]
    match = _BEFORE_NUMBER.search(text)
    if match:
        return _CURRENCY_WORDS[match.group(1)]
    folded = _fold(text)
    for code in _ISO_CODES:
        if re.search(rf"(?<![a-z0-9]){code}(?![a-z0-9])", folded):
            return _CURRENCY_WORDS[code]
    return None


def to_eur(amount: Optional[float], currency: Optional[str]) -> Optional[float]:
    """Đổi sang EUR theo bảng tỷ giá trong app/core/config.py."""
    if amount is None:
        return None
    rate = FX_UNITS_PER_EUR.get((currency or "").upper())
    if not rate:
        return None
    return float(amount) / float(rate)


def format_money(amount: Optional[float], currency: Optional[str]) -> str:
    if amount is None:
        return "—"
    code = (currency or "EUR").upper()
    if code in ("VND", "IDR"):
        return f"{amount:,.0f} {code}"
    return f"{amount:,.2f} {code}"


def normalize_trip_budget(plan, source_text: str = ""):
    """Chuẩn hoá `plan.budget` về EUR. Idempotent.

    - Có tiền tệ (khai báo trong `budget_currency`, hoặc tìm thấy trong `source_text`)
      thì quy đổi và lưu số gốc vào `budget_original`.
    - Không rõ tiền tệ, hoặc đã là EUR, hoặc đã chuẩn hoá rồi thì trả plan nguyên vẹn.
    """
    if plan is None or getattr(plan, "budget_original", None) is not None:
        return plan

    declared = (getattr(plan, "budget_currency", None) or "").upper() or None
    currency = declared or detect_currency(source_text)
    if currency in (None, "EUR"):
        return plan

    amount = getattr(plan, "budget", None)
    if amount is None:
        amount = parse_amount(source_text)
    converted = to_eur(amount, currency)
    if converted is None:
        return plan

    if getattr(plan, "budget_original", None) is None:
        plan.budget_original = float(amount)
    plan.budget_currency = currency
    plan.budget = round(converted, 2)

    daily = getattr(plan, "daily_spending_budget", None)
    if daily:
        converted_daily = to_eur(daily, currency)
        if converted_daily is not None:
            plan.daily_spending_budget = round(converted_daily, 2)
    return plan


def budget_label(plan) -> str:
    """Nhãn ngân sách để hiển thị, ví dụ '€1,052.63 (từ 30,000,000 VND)'."""
    if plan is None or getattr(plan, "budget", None) is None:
        return "Not specified"
    base = f"€{plan.budget:,.2f}"
    original = getattr(plan, "budget_original", None)
    currency = (getattr(plan, "budget_currency", None) or "").upper()
    if original is not None and currency not in ("", "EUR"):
        return f"{base} (from {format_money(original, currency)})"
    return base
