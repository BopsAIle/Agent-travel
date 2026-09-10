import os
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Any, List, Optional

from flight_display import (
    format_flight_options_markdown,
    search_flights_for_slots,
    user_wants_flight_list,
)
from quality import sanitize_reply
from schemas import EventInfo, HotelInfo, LOOKUP_TARGETS
from telemetry import agent_scope, tracked_post

HOTEL_SERVICE_URL = os.getenv("HOTEL_SERVICE_URL", "http://hotel-service:8001")
EVENT_SERVICE_URL = os.getenv("EVENT_SERVICE_URL", "http://event-service:8004")
ACTIVITY_SERVICE_URL = os.getenv("ACTIVITY_SERVICE_URL", "http://activity-service:8002")

LOOKUP_REQUIRED = {
    "flight": ("origin", "destination", "start_date"),
    "hotel": ("destination", "start_date", "end_date"),
    "event": ("destination", "start_date"),
    "activity": ("destination",),
}

DEFAULT_ACTIVITY_INTERESTS = ["famous attractions", "entertainment"]

_FLIGHT_HINT = re.compile(
    r"(chuyen\s*bay|ve\s*may\s*bay|\bflights?\b|thoi\s*gian\s*bay|gio\s*bay|gia\s*ve)",
    re.I,
)
_HOTEL_HINT = re.compile(r"(khach\s*san|\bhotels?\b|noi\s*o|phong\s*nghi)", re.I)
_EVENT_HINT = re.compile(r"(su\s*kien|concert|festival|ticketmaster|\bevents?\b)", re.I)
_ACTIVITY_HINT = re.compile(
    r"(vui\s*choi|giai\s*tri|hoat\s*dong|dia\s*diem|attractions?|"
    r"things\s*to\s*do|noi\s*tieng|tham\s*quan)",
    re.I,
)
_RESULTS_HINT = re.compile(
    r"(xuat\s*ra|liet\s*ke|ket\s*qua|cho\s*(toi|minh)\s*(xem|danh\s*sach)|"
    r"\bshow\b|\blist\b|display|tra\s*loi)",
    re.I,
)
_SHORTEST_HINT = re.compile(r"(ngan\s*nhat|nhanh\s*nhat|shortest|fastest)", re.I)

FIELD_LABELS = {
    "en": {
        "origin": "departure city",
        "destination": "destination",
        "start_date": "start date",
        "end_date": "end date",
    },
    "vi": {
        "origin": "điểm đi",
        "destination": "điểm đến",
        "start_date": "ngày đi",
        "end_date": "ngày về / trả phòng",
    },
}


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text or "")
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn").lower()


def _lang(value: Optional[str]) -> str:
    if not value:
        return "en"
    code = value.strip().lower().replace("_", "-")
    if "-" in code:
        code = code.split("-", 1)[0]
    return code or "en"


def _field(obj: Any, key: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        value = obj.get(key, default)
        return default if value is None else value
    return getattr(obj, key, default)


def _plus_days(date_str: str, days: int) -> str:
    parsed = datetime.strptime(date_str, "%Y-%m-%d")
    return (parsed + timedelta(days=days)).strftime("%Y-%m-%d")


def _year_of(slots: dict) -> Optional[str]:
    start = str((slots or {}).get("start_date") or "")
    if len(start) >= 4 and start[:4].isdigit():
        return start[:4]
    return None


def normalize_lookup_targets(targets: Optional[List[str]]) -> List[str]:
    ordered = []
    for item in targets or []:
        name = "activity" if item == "activities" else str(item or "").strip().lower()
        if name in LOOKUP_TARGETS and name not in ordered:
            ordered.append(name)
    return ordered


def missing_lookup_fields(slots: dict, targets: List[str]) -> List[str]:
    missing = []
    for target in targets:
        for key in LOOKUP_REQUIRED.get(target, ()):
            value = (slots or {}).get(key)
            if (value is None or value == "") and key not in missing:
                missing.append(key)
    return missing


def infer_lookup_targets(
    user_message: str,
    messages: Optional[List[dict]] = None,
    slots: Optional[dict] = None,
) -> List[str]:
    text = _fold(user_message)
    targets: List[str] = []
    if _FLIGHT_HINT.search(text) or user_wants_flight_list(user_message, messages):
        targets.append("flight")
    if _HOTEL_HINT.search(text):
        targets.append("hotel")
    if _EVENT_HINT.search(text):
        targets.append("event")
    if _ACTIVITY_HINT.search(text):
        targets.append("activity")
    if targets:
        return targets
    if not _RESULTS_HINT.search(text):
        return []
    slots = slots or {}
    if slots.get("origin") and slots.get("destination") and slots.get("start_date"):
        return ["flight"]
    if slots.get("destination") and slots.get("start_date") and slots.get("end_date"):
        return ["hotel"]
    if slots.get("destination"):
        return ["activity"]
    return []


def _missing_lookup_question(language: str, missing: List[str]) -> str:
    lang = language if language in FIELD_LABELS else "en"
    labels = FIELD_LABELS[lang]
    named = [labels.get(item, item) for item in missing]
    joined = ", ".join(named)
    if lang == "vi":
        return f"Mình còn thiếu {joined} để tìm đúng thứ bạn hỏi. Bạn cho mình biết thêm được không?"
    return f"I still need {joined} to look that up. Could you share it?"


def _empty_lookup_message(language: str, targets: List[str]) -> str:
    lang = _lang(language)
    if "flight" in targets:
        if lang == "vi":
            return (
                "Mình chưa lấy được chuyến bay phù hợp. "
                "Bạn thử thành phố cụ thể hơn (ví dụ New York thay vì Mỹ) hoặc đổi ngày nhé."
            )
        return (
            "I could not find matching flights. "
            "Try a specific city (for example New York instead of the USA) or another date."
        )
    if lang == "vi":
        return "Mình chưa tìm được kết quả phù hợp. Bạn nói rõ hơn địa điểm hoặc thời gian giúp mình nhé."
    return "I could not find matching results. A more specific place or date would help."


def _replace_last_assistant(session, content: str) -> None:
    for item in reversed(session.messages or []):
        if item.get("role") == "assistant":
            item["content"] = content
            return
    session.messages.append({"role": "assistant", "content": content})


def _wants_shortest(user_message: str, messages: Optional[List[dict]]) -> bool:
    if _SHORTEST_HINT.search(_fold(user_message)):
        return True
    for item in reversed(messages or []):
        if item.get("role") == "user" and _SHORTEST_HINT.search(_fold(str(item.get("content") or ""))):
            return True
    return False


def _search_hotels(slots: dict) -> List[HotelInfo]:
    destination = (slots or {}).get("destination")
    start_date = (slots or {}).get("start_date")
    end_date = (slots or {}).get("end_date")
    person = (slots or {}).get("person") or 1
    if not destination or not start_date:
        return []
    if not end_date or end_date == start_date:
        try:
            end_date = _plus_days(start_date, 1)
        except ValueError:
            return []
    try:
        person = max(int(person), 1)
    except (TypeError, ValueError):
        person = 1
    try:
        response = tracked_post(
            f"{HOTEL_SERVICE_URL.rstrip('/')}/search",
            json={
                "destination": destination,
                "start_date": start_date,
                "end_date": end_date,
                "person": person,
            },
            timeout=60,
        )
        response.raise_for_status()
        return [HotelInfo(**item) for item in (response.json() or [])]
    except Exception as exc:
        print(f"-> Hotel lookup failed: {exc}")
        return []


def _search_events(slots: dict) -> List[EventInfo]:
    city = (slots or {}).get("destination")
    start_date = (slots or {}).get("start_date")
    end_date = (slots or {}).get("end_date")
    if not city or not start_date:
        return []
    if not end_date or end_date == start_date:
        try:
            end_date = _plus_days(start_date, 30)
        except ValueError:
            end_date = start_date
    try:
        response = tracked_post(
            f"{EVENT_SERVICE_URL.rstrip('/')}/search_events",
            json={"city": city, "start_date": start_date, "end_date": end_date},
            timeout=30,
        )
        response.raise_for_status()
        return [EventInfo(**item) for item in (response.json() or [])]
    except Exception as exc:
        print(f"-> Event lookup failed: {exc}")
        return []


def _search_activities(slots: dict) -> str:
    destination = str((slots or {}).get("destination") or "").strip()
    if not destination:
        return ""
    interests = list((slots or {}).get("interests") or [])
    interests = [item for item in interests if str(item).strip()]
    if not interests:
        interests = list(DEFAULT_ACTIVITY_INTERESTS)
    year = _year_of(slots)
    query_dest = f"{destination} {year}" if year else destination
    try:
        response = tracked_post(
            f"{ACTIVITY_SERVICE_URL.rstrip('/')}/search_activities",
            json={"destination": query_dest, "interests": interests},
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, str) else str(data or "")
    except Exception as exc:
        print(f"-> Activity lookup failed: {exc}")
        return ""


def _format_hotels(hotels: List[HotelInfo], language: str, limit: int = 8) -> str:
    if not hotels:
        return ""
    lang = _lang(language)
    header = "**Khách sạn:**" if lang == "vi" else "**Hotels:**"
    lines = [header]
    for index, item in enumerate(hotels[:limit], 1):
        name = _field(item, "hotel_name", "") or "Hotel"
        rating = _field(item, "rating", "")
        word = _field(item, "rating_word", "")
        total = _field(item, "total_price", 0) or 0
        try:
            price_text = f"€{float(total):,.2f}"
        except (TypeError, ValueError):
            price_text = str(total)
        extra = " ".join(part for part in (str(rating), str(word)) if part)
        lines.append(f"{index}. {name} — {price_text}" + (f" ({extra})" if extra else ""))
    return "\n".join(lines)


def _format_events(events: List[EventInfo], language: str, limit: int = 10) -> str:
    if not events:
        return ""
    lang = _lang(language)
    header = "**Sự kiện:**" if lang == "vi" else "**Events:**"
    lines = [header]
    for index, item in enumerate(events[:limit], 1):
        name = _field(item, "name", "") or "Event"
        date = _field(item, "date", "") or ""
        venue = _field(item, "venue", "") or ""
        url = _field(item, "url", "") or ""
        line = f"{index}. {name}"
        if date:
            line += f" ({date})"
        if venue:
            line += f" — {venue}"
        if url and url != "#":
            line += f"\n   {url}"
        lines.append(line)
    return "\n".join(lines)


def _format_activities(raw: str, language: str, limit: int = 8) -> str:
    text = (raw or "").strip()
    if not text or "No relevant activities found" in text:
        return ""
    lang = _lang(language)
    header = "**Gợi ý vui chơi / địa điểm:**" if lang == "vi" else "**Things to do:**"
    titles = re.findall(r"Title:\s*(.+)", text)
    contents = re.findall(r"Content:\s*(.+)", text)
    if titles:
        lines = [header]
        for index, title in enumerate(titles[:limit], 1):
            snippet = contents[index - 1].strip() if index - 1 < len(contents) else ""
            snippet = sanitize_reply(snippet, max_chars=220)
            line = f"{index}. {title.strip()}"
            if snippet:
                line += f" — {snippet}"
            lines.append(line)
        return "\n".join(lines)
    return f"{header}\n{sanitize_reply(text, max_chars=3500)}"


def _intro(language: str, targets: List[str]) -> str:
    lang = _lang(language)
    if lang == "vi":
        labels = {
            "flight": "chuyến bay",
            "hotel": "khách sạn",
            "event": "sự kiện",
            "activity": "địa điểm vui chơi",
        }
        named = [labels[item] for item in targets if item in labels]
        joined = ", ".join(named) if named else "kết quả"
        return f"Đây là {joined} mình tìm được từ dữ liệu thật:"
    labels = {
        "flight": "flights",
        "hotel": "hotels",
        "event": "events",
        "activity": "places to visit",
    }
    named = [labels[item] for item in targets if item in labels]
    joined = ", ".join(named) if named else "results"
    return f"Here are the {joined} I found from live data:"


def apply_lookup(session, turn, user_message: str):
    """Attach live flight/hotel/event/activity results for a lookup turn."""
    if getattr(turn, "intent", None) in ("place", "recall", "plan", "refine"):
        return turn

    targets = normalize_lookup_targets(getattr(turn, "lookup_targets", None))
    if not targets:
        targets = infer_lookup_targets(user_message, session.messages, session.slots)
    if not targets:
        return turn

    turn.intent = "lookup"
    turn.ready_to_plan = False
    turn.lookup_targets = targets
    language = _lang(getattr(turn, "detected_language", None) or session.language)
    if session.slots is None:
        session.slots = {}
    if any(item in targets for item in ("activity", "event")) and not session.slots.get("start_date"):
        year_match = re.search(r"\b(20\d{2})\b", user_message or "")
        if year_match:
            session.slots["start_date"] = f"{year_match.group(1)}-01-01"
    missing = missing_lookup_fields(session.slots or {}, targets)
    if missing:
        turn.reply = _missing_lookup_question(language, missing)
        _replace_last_assistant(session, turn.reply)
        return turn

    sections: List[str] = []
    with agent_scope("lookup"):
        if "flight" in targets:
            flights = search_flights_for_slots(session.slots or {})
            if _wants_shortest(user_message, session.messages):
                flights = sorted(
                    flights,
                    key=lambda item: int(_field(item, "total_duration_minutes", 0) or 0),
                )
            if flights:
                if session.trip_state is None:
                    session.trip_state = {}
                session.trip_state["flight_options"] = flights
                if not session.trip_state.get("selected_flight"):
                    session.trip_state["selected_flight"] = flights[0]
            listing = format_flight_options_markdown(flights, language)
            if listing:
                sections.append(listing)
        if "hotel" in targets:
            hotels = _search_hotels(session.slots or {})
            listing = _format_hotels(hotels, language)
            if listing:
                sections.append(listing)
        if "event" in targets:
            events = _search_events(session.slots or {})
            listing = _format_events(events, language)
            if listing:
                sections.append(listing)
        if "activity" in targets:
            raw = _search_activities(session.slots or {})
            listing = _format_activities(raw, language)
            if listing:
                sections.append(listing)

    if sections:
        turn.reply = f"{_intro(language, targets)}\n\n" + "\n\n".join(sections)
    else:
        turn.reply = _empty_lookup_message(language, targets)
    turn.reply = sanitize_reply(turn.reply)
    _replace_last_assistant(session, turn.reply)
    return turn
