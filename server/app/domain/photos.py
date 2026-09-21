"""Chuẩn hoá và kiểm chứng URL ảnh khách sạn trước khi ghi vào report.

Ảnh Booking.com là URL có chữ ký:

    https://cf.bstatic.com/xdata/images/hotel/square60/881342703.jpg?k=<64 hex>&o=

Đổi size trong đường dẫn (`square60` → `max500`) vẫn hợp lệ — chữ ký không phủ phần
size (đã probe thật) — nhưng **chữ ký phải đúng nguyên văn**. Lệch một ký tự là CDN
trả HTTP 401 và trình duyệt hiện biểu tượng ảnh vỡ, đúng lỗi ngày 21/09/2026:
xem `docs/diagnostics/2026-09-21-hotel-photo-url-broken.md`.

Report được lưu lại (`sessions.markdown_report`) và hiển thị lại nhiều lần, nên một
URL hỏng nằm trong đó thì hỏng mãi. Vì vậy trước khi ghi report, hỏi thẳng CDN xem
URL còn dùng được không; chỉ bỏ ảnh khi CDN đã từ chối rõ ràng.
"""
from __future__ import annotations

from typing import Callable, Optional

import requests

PHOTO_PROBE_TIMEOUT_SECONDS = 4

# Size nhỏ mà API trả về → size lớn hơn cho report.
SIZE_UPGRADES = (
    ("square60", "max500"),
    ("square90", "max500"),
    ("square200", "max500"),
)

# CDN từ chối dứt khoát: chữ ký sai/hết hạn, hoặc ảnh đã bị xoá.
REJECTED_STATUS_CODES = frozenset({401, 403, 404, 410})

Probe = Callable[[str, float], Optional[int]]


def normalize_photo_url(url: object) -> str:
    """URL ảnh ở size hiển thị được, hoặc "" nếu không có ảnh."""
    text = str(url or "").strip()
    if not text or text.lower() in ("none", "null"):
        return ""
    for small, large in SIZE_UPGRADES:
        text = text.replace(small, large)
    return text


def _http_probe(url: str, timeout: float) -> Optional[int]:
    """Mã HTTP của URL, hoặc None nếu không hỏi được (mạng lỗi/timeout/HEAD bị chặn)."""
    try:
        response = requests.head(url, timeout=timeout, allow_redirects=True)
    except requests.RequestException:
        return None
    status = response.status_code
    response.close()
    # 405 = CDN không nhận HEAD: không kết luận được gì về ảnh.
    return None if status == 405 else status


def photo_is_rejected(
    url: str,
    *,
    timeout: float = PHOTO_PROBE_TIMEOUT_SECONDS,
    probe: Optional[Probe] = None,
) -> bool:
    """True chỉ khi CDN trả lỗi dứt khoát cho URL này."""
    status = (probe or _http_probe)(url, timeout)
    return status in REJECTED_STATUS_CODES


def verified_photo_url(
    url: object,
    *,
    timeout: float = PHOTO_PROBE_TIMEOUT_SECONDS,
    probe: Optional[Probe] = None,
) -> str:
    """URL ảnh dùng được, hoặc "" nếu CDN đã từ chối.

    Không kết luận được (mạng lỗi, timeout, HEAD 405) thì GIỮ ảnh: thà để trình duyệt
    tự thử — giao diện đã có fallback — còn hơn xoá một ảnh tốt vì một lần probe hỏng.
    """
    text = normalize_photo_url(url)
    if not text:
        return ""
    if photo_is_rejected(text, timeout=timeout, probe=probe):
        return ""
    return text
