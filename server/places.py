import re
from typing import Any, List, Optional

from quality import significant_tokens

INDEX_PATTERNS = [
    re.compile(
        r"(?:địa\s*điểm|dia\s*diem|điểm|diem|location|place|stop|activity|hoạt\s*động)\s*"
        r"(?:số|so|#|number|thứ|thu)?\s*(\d{1,2})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:số|so|#)\s*(\d{1,2})\s*(?:trong\s*(?:lịch\s*trình|danh\s*sách)|on\s*(?:the\s*)?(?:itinerary|list))",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:no\.?|number)\s*(\d{1,2})\b", re.IGNORECASE),
]

PLACE_ASK_RE = re.compile(
    r"(nói\s*kỹ|nói\s*chi\s*tiết|chi\s*tiết|giới\s*thiệu|"
    r"tell\s*me\s*(more\s*)?about|describe|what(?:'s|\s+is)|details?\s+about)",
    re.IGNORECASE,
)

PLACE_NOUN_RE = re.compile(
    r"(địa\s*điểm|dia\s*diem|điểm|location|place|landmark|attraction|tower|bảo\s*tàng|museum)",
    re.IGNORECASE,
)


def _field(obj: Any, key: str, default=None):
    if obj is None:
        return default
    if hasattr(obj, key):
        value = getattr(obj, key)
        return default if value is None else value
    if isinstance(obj, dict):
        value = obj.get(key, default)
        return default if value is None else value
    return default


def destination_of(trip_state: Optional[dict]) -> str:
    if not trip_state:
        return ""
    plan = trip_state.get("trip_plan")
    return str(_field(plan, "destination", "") or "")


def _as_place(index: int, activity: Any, day: Optional[int] = None) -> dict:
    lat = _field(activity, "latitude")
    lon = _field(activity, "longitude")
    name = str(_field(activity, "name", "") or "").strip()
    maps_url = ""
    if lat and lon:
        maps_url = f"https://www.google.com/maps?q={lat},{lon}"
    elif name:
        maps_url = f"https://www.google.com/maps/search/?api=1&query={name.replace(' ', '+')}"
    return {
        "index": index,
        "day": day,
        "name": name,
        "description": str(_field(activity, "description", "") or "").strip(),
        "location": str(_field(activity, "location", "") or "").strip(),
        "time_of_day": str(_field(activity, "time_of_day", "") or "").strip(),
        "latitude": lat,
        "longitude": lon,
        "maps_url": maps_url,
    }


def list_itinerary_places(trip_state: Optional[dict]) -> List[dict]:
    if not trip_state:
        return []
    itinerary = trip_state.get("final_itinerary")
    daily_plans = _field(itinerary, "daily_plans", None) if itinerary else None
    places: List[dict] = []
    index = 1
    if daily_plans:
        for day_plan in daily_plans:
            day = _field(day_plan, "day")
            for activity in _field(day_plan, "activities", []) or []:
                places.append(_as_place(index, activity, day))
                index += 1
        return places
    for activity in trip_state.get("extracted_activities") or []:
        places.append(_as_place(index, activity))
        index += 1
    return places


def catalog_text(places: List[dict]) -> str:
    if not places:
        return "No numbered places in the current itinerary."
    lines = []
    for place in places:
        day = f" (day {place['day']})" if place.get("day") else ""
        extra = place.get("description") or place.get("location") or ""
        suffix = f": {extra}" if extra else ""
        lines.append(f"{place['index']}. {place['name']}{day}{suffix}")
    return "\n".join(lines)


def extract_place_index(message: str) -> Optional[int]:
    text = message or ""
    for pattern in INDEX_PATTERNS:
        match = pattern.search(text)
        if match:
            try:
                value = int(match.group(1))
            except (TypeError, ValueError):
                continue
            if 1 <= value <= 40:
                return value
    return None


def looks_like_place_request(message: str) -> bool:
    text = message or ""
    if extract_place_index(text):
        return True
    if PLACE_ASK_RE.search(text) and PLACE_NOUN_RE.search(text):
        return True
    return False


def _best_name_match(places: List[dict], query: str) -> Optional[dict]:
    needle = (query or "").strip().lower()
    if not needle or not places:
        return None
    for place in places:
        name = (place.get("name") or "").lower()
        if name and (name in needle or needle in name):
            return place
    query_tokens = significant_tokens(query)
    if not query_tokens:
        return None
    ranked = []
    for place in places:
        name_tokens = significant_tokens(place.get("name") or "")
        overlap = query_tokens & name_tokens
        if overlap:
            ranked.append((len(overlap), place))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]


def resolve_place(
    trip_state: Optional[dict],
    place_index: Optional[int] = None,
    place_query: Optional[str] = None,
    user_message: str = "",
) -> Optional[dict]:
    places = list_itinerary_places(trip_state)
    index = place_index or extract_place_index(user_message)
    if index and 1 <= index <= len(places):
        return places[index - 1]
    query = place_query or user_message
    matched = _best_name_match(places, query)
    if matched:
        return matched
    if index and places:
        return None
    return None
