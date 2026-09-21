import os
from datetime import datetime
from typing import Any, List, Optional

import requests

from schemas import HotelInfo


RAPIDAPI_HOST = "booking-com18.p.rapidapi.com"
REQUEST_TIMEOUT_SECONDS = 20


class HotelProviderError(RuntimeError):
    """Safe, structured error raised when Booking.com cannot serve hotel data."""

    def __init__(self, code: str, message: str, status_code: Optional[int] = None):
        self.code = code
        self.status_code = status_code
        super().__init__(f"{code}: {message}")


def _rapid_headers() -> dict:
    key = (os.getenv("RAPIDAPI_KEY") or "").strip()
    if not key:
        raise HotelProviderError(
            "provider_unauthorized", "RapidAPI key is missing.", status_code=401
        )
    return {
        "x-rapidapi-key": key,
        "x-rapidapi-host": RAPIDAPI_HOST,
    }


def _provider_error(status_code: int) -> HotelProviderError:
    if status_code == 401:
        return HotelProviderError(
            "provider_unauthorized", "RapidAPI rejected the API key.", status_code
        )
    if status_code == 403:
        return HotelProviderError(
            "provider_not_subscribed",
            "This RapidAPI account is not subscribed to booking-com18.",
            status_code,
        )
    if status_code == 429:
        return HotelProviderError(
            "provider_rate_limited", "RapidAPI quota or rate limit was reached.", status_code
        )
    if status_code == 400:
        return HotelProviderError(
            "provider_bad_request", "Booking.com rejected the search parameters.", status_code
        )
    return HotelProviderError(
        "provider_unavailable", f"Booking.com returned HTTP {status_code}.", status_code
    )


def _request_json(url: str, params: dict) -> dict:
    try:
        response = requests.get(
            url,
            headers=_rapid_headers(),
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise HotelProviderError(
            "provider_unavailable", "Could not connect to Booking.com."
        ) from exc
    if not response.ok:
        raise _provider_error(response.status_code)
    try:
        payload = response.json()
    except (TypeError, ValueError) as exc:
        raise HotelProviderError(
            "provider_unavailable", "Booking.com returned an invalid response."
        ) from exc
    return payload if isinstance(payload, dict) else {}


def _result_rows(payload: dict) -> List[dict]:
    data: Any = payload.get("data")
    if isinstance(data, dict):
        data = data.get("hotels") or data.get("results") or []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def find_location_id(city_name: str) -> Optional[str]:
    """Tra ve token `id` (opaque) cua mot thanh pho.

    `/stays/auto-complete` tra ve HAI field cung trong nhu "ma dia diem":
      * `id`      — envelope JSON base64; DAY la gia tri `/stays/search` chap nhan.
      * `dest_id` — so nhu "-716583"; trong giong ma hon nhung `/stays/search`
                    tra 400 "Location is not available".

    Da kiem chung bang cach goi that ca hai: `id` -> HTTP 200, `dest_id` -> HTTP 400.
    Dung doi ham nay sang tra `dest_id`.
    """
    print(f"--- Finding Location ID for {city_name} ---")
    payload = _request_json(
        f"https://{RAPIDAPI_HOST}/stays/auto-complete", {"query": city_name}
    )
    rows = _result_rows(payload)
    if not rows:
        return None
    location_id = rows[0].get("id")
    return str(location_id) if location_id not in (None, "") else None


def search_hotels_at(
    location_id: str,
    start_date: str,
    end_date: str,
    adults: int,
    children_ages: Optional[List[int]] = None,
) -> List[HotelInfo]:
    print(f"Searching hotels with ID: {location_id}")
    params = {
        "locationId": location_id,
        "checkinDate": start_date,
        "checkoutDate": end_date,
        "adults": str(adults),
        "sortBy": "bayesian_review_score",
        "currencyCode": "EUR",
    }
    # Da thu that: `children` nhan danh sach TUOI cach nhau dau phay ("5,7") va duoc
    # tinh tien; `childrenAges` bi bo qua. Khong bao gio bia tuoi.
    if children_ages:
        params["children"] = ",".join(str(age) for age in children_ages)
    payload = _request_json(f"https://{RAPIDAPI_HOST}/stays/search", params)
    try:
        nights = max(
            1,
            (datetime.strptime(end_date, "%Y-%m-%d") - datetime.strptime(start_date, "%Y-%m-%d")).days,
        )
    except ValueError as exc:
        raise HotelProviderError(
            "provider_bad_request", "Hotel dates must use YYYY-MM-DD."
        ) from exc

    results = []
    for hotel_data in _result_rows(payload)[:10]:
        price_breakdown = hotel_data.get("priceBreakdown") or {}
        total_price = (price_breakdown.get("grossPrice") or {}).get("value") or 0
        try:
            total_price = float(total_price)
        except (TypeError, ValueError):
            total_price = 0.0

        photo_urls = hotel_data.get("photoUrls") or []
        photo_url = photo_urls[0] if photo_urls else None
        static_map_url = None
        lat = hotel_data.get("latitude")
        lon = hotel_data.get("longitude")
        if lat is not None and lon is not None:
            static_map_url = (
                "https://staticmap.openstreetmap.de/staticmap.php"
                f"?center={lat},{lon}&zoom=15&size=600x300&marker={lat},{lon},red-pushpin"
            )

        results.append(
            HotelInfo(
                hotel_name=hotel_data.get("name", "Unknown Hotel"),
                price_per_night=round(total_price / nights, 2),
                total_price=round(total_price, 2),
                rating=hotel_data.get("reviewScore", 0) or 0,
                review_count=hotel_data.get("reviewCount", 0) or 0,
                rating_word=hotel_data.get("reviewScoreWord", "") or "",
                main_photo_url=photo_url,
                static_map_url=static_map_url,
            )
        )
    print(f"Found {len(results)} hotels.")
    return results
