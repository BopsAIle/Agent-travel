import os
import re
import unicodedata
from typing import Any, List, Optional

from schemas import FlightInfo
from telemetry import tracked_post

FLIGHT_SERVICE_URL = os.getenv("FLIGHT_SERVICE_URL", "http://flight-service:8000")

_SHOW_RE = re.compile(
    r"(hien\s*thi|liet\s*ke|cho\s*(toi|minh)\s*xem|show|list|display|"
    r"xem\s*(cac\s*)?(chuyen|ve))",
    re.IGNORECASE,
)
_FLIGHT_RE = re.compile(r"(chuyen\s*bay|ve\s*may\s*bay|\bflights?\b)", re.IGNORECASE)


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


def _duration(minutes: Any) -> str:
    try:
        total = int(minutes or 0)
    except (TypeError, ValueError):
        return ""
    hours, mins = divmod(max(total, 0), 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"


def _leg_text(leg: Any) -> str:
    if not leg:
        return ""
    airline = str(_field(leg, "airline", "") or "").strip()
    number = str(_field(leg, "flight_number", "") or "").strip()
    carrier = " ".join(part for part in (airline, number) if part)
    dep_time = _field(leg, "departure_time", "")
    arr_time = _field(leg, "arrival_time", "")
    dep_air = _field(leg, "departure_airport", "")
    arr_air = _field(leg, "arrival_airport", "")
    duration = _duration(_field(leg, "duration_minutes", 0))
    extra = ""
    if _field(leg, "is_layover"):
        layover = _field(leg, "layover_airport", "") or ""
        wait = _duration(_field(leg, "layover_duration_minutes", 0))
        extra = f"; layover {layover} {wait}".rstrip()
    return f"{carrier}: {dep_time} {dep_air} → {arr_time} {arr_air} ({duration}{extra})"


def format_flight_options_markdown(
    flights: Optional[List[Any]],
    language: Optional[str] = "en",
    limit: int = 10,
) -> str:
    if not flights:
        return ""
    lang = _lang(language)
    header = (
        "**Các chuyến bay từ Booking.com:**"
        if lang == "vi"
        else "**Flights from Booking.com:**"
    )
    return_label = "Về" if lang == "vi" else "Return"
    lines = [header]
    for index, item in enumerate(flights[:limit], 1):
        price = _field(item, "price", 0) or 0
        try:
            price_text = f"€{float(price):,.2f}"
        except (TypeError, ValueError):
            price_text = str(price)
        outbound = _leg_text(_field(item, "departure_leg"))
        ret = _field(item, "return_leg")
        line = f"{index}. {outbound} — {price_text}"
        if ret:
            line += f"\n   {return_label}: {_leg_text(ret)}"
        lines.append(line)
    return "\n".join(lines)


def compact_flight_digest(flights: Optional[List[Any]], limit: int = 8) -> str:
    if not flights:
        return ""
    lines = [f"Booking.com flight options ({min(len(flights), limit)}):"]
    for index, item in enumerate(flights[:limit], 1):
        dep = _field(item, "departure_leg") or {}
        airline = _field(dep, "airline", "") or "Unknown"
        number = _field(dep, "flight_number", "") or ""
        dep_air = _field(dep, "departure_airport", "")
        arr_air = _field(dep, "arrival_airport", "")
        price = _field(item, "price", 0) or 0
        lines.append(f"{index}. {airline} {number} {dep_air} → {arr_air} €{price}")
    return "\n".join(lines)


def user_wants_flight_list(user_message: str, messages: Optional[List[dict]]) -> bool:
    text = _fold(user_message or "")
    if _FLIGHT_RE.search(text) and (
        _SHOW_RE.search(text) or re.search(r"\b(ok|okay|duoc|u|yes)\b", text, re.I)
    ):
        return True
    if not _SHOW_RE.search(text):
        return False
    for item in reversed(messages or []):
        if item.get("role") == "assistant":
            return bool(_FLIGHT_RE.search(_fold(str(item.get("content") or ""))))
    return False


def search_flights_for_slots(slots: dict) -> List[FlightInfo]:
    origin = (slots or {}).get("origin")
    destination = (slots or {}).get("destination")
    start_date = (slots or {}).get("start_date")
    end_date = (slots or {}).get("end_date") or start_date
    person = (slots or {}).get("person") or 1
    if not origin or not destination or not start_date:
        return []
    try:
        person = int(person)
    except (TypeError, ValueError):
        person = 1
    payload = {
        "origin": origin,
        "destination": destination,
        "start_date": start_date,
        "end_date": end_date,
        "person": max(person, 1),
    }
    try:
        response = tracked_post(
            f"{FLIGHT_SERVICE_URL.rstrip('/')}/search",
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        return [FlightInfo(**item) for item in (response.json() or [])]
    except Exception as exc:
        print(f"-> Flight list search failed: {exc}")
        return []


def _replace_last_assistant(session, content: str) -> None:
    for item in reversed(session.messages or []):
        if item.get("role") == "assistant":
            item["content"] = content
            return
    session.messages.append({"role": "assistant", "content": content})


def attach_booking_flights_if_requested(session, turn, user_message: str):
    """Replace a 'I'll summarize flights' reply with the actual Booking.com list."""
    if getattr(turn, "intent", None) == "place":
        return turn
    if not user_wants_flight_list(user_message, session.messages):
        return turn

    language = _lang(getattr(turn, "detected_language", None) or session.language)
    trip_state = session.trip_state or {}
    flights = list(trip_state.get("flight_options") or [])
    if not flights:
        flights = search_flights_for_slots(session.slots or {})
        if flights:
            if session.trip_state is None:
                session.trip_state = {}
            session.trip_state["flight_options"] = flights
            if not session.trip_state.get("selected_flight"):
                session.trip_state["selected_flight"] = flights[0]

    listing = format_flight_options_markdown(flights, language)
    turn.intent = "chat"
    turn.ready_to_plan = False
    prefix = (turn.reply or "").strip()
    if listing:
        turn.reply = f"{prefix}\n\n{listing}" if prefix else listing
    elif language == "vi":
        turn.reply = (
            "Mình chưa lấy được danh sách chuyến bay từ Booking.com. "
            "Bạn cho mình điểm đi, điểm đến và ngày bay (một chiều thì chỉ cần ngày đi) nhé."
        )
    else:
        turn.reply = (
            "I do not have Booking.com flight results yet. "
            "Tell me origin, destination, and the travel date "
            "(one-way only needs a departure date)."
        )
    _replace_last_assistant(session, turn.reply)
    return turn
