"""Stable planning failure codes and user-facing explanations."""

from typing import List, Optional


MESSAGES = {
    "en": {
        "hotel:provider_unauthorized": "Hotel search failed because RapidAPI authentication was rejected. Check RAPIDAPI_KEY.",
        "hotel:provider_not_subscribed": "Hotel search failed because this RapidAPI account is not subscribed to booking-com18.",
        "hotel:provider_rate_limited": "Hotel search is temporarily unavailable because the RapidAPI quota or rate limit was reached.",
        "hotel:provider_bad_request": "Hotel search was rejected because the provider did not accept the location or dates.",
        "hotel:provider_unavailable": "The hotel provider is temporarily unavailable.",
        "hotel:no_results": "No hotels were found for the requested destination and dates.",
        "flight:no_results": "No flights were found for the requested route and dates.",
        "flight:provider_unavailable": "The flight provider is temporarily unavailable.",
        "hotel:location_id_not_from_lookup": "Hotel search stopped before contacting the provider: the destination location token was not accepted locally. The fallback search was used instead.",
        "hotel:missing": "A hotel could not be selected.",
        "flight:missing": "A flight could not be selected.",
    },
    "vi": {
        "hotel:provider_unauthorized": "Không lấy được dữ liệu khách sạn vì RapidAPI từ chối xác thực. Hãy kiểm tra RAPIDAPI_KEY.",
        "hotel:provider_not_subscribed": "Không lấy được dữ liệu khách sạn vì tài khoản RapidAPI này chưa đăng ký booking-com18.",
        "hotel:provider_rate_limited": "Tạm thời không lấy được dữ liệu khách sạn vì RapidAPI đã hết hạn mức hoặc bị giới hạn tần suất.",
        "hotel:provider_bad_request": "Dịch vụ khách sạn từ chối địa điểm hoặc ngày tìm kiếm được gửi lên.",
        "hotel:provider_unavailable": "Dịch vụ cung cấp dữ liệu khách sạn đang tạm thời không khả dụng.",
        "hotel:no_results": "Không tìm thấy khách sạn cho địa điểm và ngày đã chọn.",
        "flight:no_results": "Không tìm thấy chuyến bay cho chặng và ngày đã chọn.",
        "flight:provider_unavailable": "Dịch vụ cung cấp dữ liệu chuyến bay đang tạm thời không khả dụng.",
        "hotel:location_id_not_from_lookup": "Chưa lấy được mã địa điểm khách sạn nên chưa gọi được nhà cung cấp. Hệ thống đã thử lại bằng đường dự phòng.",
        "hotel:missing": "Không thể chọn được khách sạn.",
        "flight:missing": "Không thể chọn được chuyến bay.",
    },
}


def classify_provider_error(error: str) -> str:
    text = (error or "").casefold()
    # `location_id_not_from_lookup` la loi guard noi bo cua hotel-service, KHONG
    # phai loi cua nha cung cap: no xay ra truoc khi goi Booking.com. Neu gop no
    # vao `provider_bad_request` thi thong bao cho nguoi dung se noi sai su that.
    for code in (
        "provider_unauthorized",
        "provider_not_subscribed",
        "provider_rate_limited",
        "provider_bad_request",
        "provider_unavailable",
        "location_id_not_from_lookup",
    ):
        if code in text:
            return code
    if "401" in text or "unauthorized" in text or "authentication" in text:
        return "provider_unauthorized"
    if "403" in text or "not subscribed" in text:
        return "provider_not_subscribed"
    if "429" in text or "rate limit" in text or "quota" in text:
        return "provider_rate_limited"
    if "400" in text or "bad request" in text:
        return "provider_bad_request"
    return "provider_unavailable"


def issue_message(kind: str, reason: str, language: Optional[str]) -> str:
    lang = "vi" if str(language or "").lower().startswith("vi") else "en"
    messages = MESSAGES[lang]
    return messages.get(f"{kind}:{reason}", messages[f"{kind}:missing"])


def collect_planning_issues(state: dict, language: Optional[str] = None) -> List[str]:
    lang = language or state.get("language") or "en"
    issues = []
    if not state.get("selected_flight"):
        reason = state.get("flight_failure_reason") or (
            "no_results" if not state.get("flight_options") else "missing"
        )
        issues.append(issue_message("flight", reason, lang))
    if not state.get("selected_hotel"):
        reason = state.get("hotel_failure_reason") or (
            "no_results" if not state.get("hotel_options") else "missing"
        )
        issues.append(issue_message("hotel", reason, lang))
    return issues
