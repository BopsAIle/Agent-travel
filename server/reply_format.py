import re
from typing import Any, List, Optional
from urllib.parse import quote_plus

from quality import looks_like_option_list, sanitize_reply

_IATA_RE = re.compile(r"\(([A-Z]{3})\)")
_AIRPORT_NOISE = re.compile(
    r"\s*(International\s+Airport|Intl\.?\s*Airport|Airport)\s*",
    re.IGNORECASE,
)


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


def _price_text(price: Any) -> str:
    try:
        return f"€{float(price):,.2f}"
    except (TypeError, ValueError):
        return str(price or "")


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


def _airport_code(value: Any) -> str:
    text = str(value or "").strip()
    match = _IATA_RE.search(text)
    if match:
        return match.group(1)
    return text


def _airport_short(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = _IATA_RE.search(text)
    code = match.group(1) if match else ""
    name = _IATA_RE.sub("", text).strip()
    name = _AIRPORT_NOISE.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip(" ,")
    if name and code:
        return f"{name} ({code})"
    return code or name or text


def _carrier(leg: Any) -> str:
    if not leg:
        return "Flight"
    airline = str(_field(leg, "airline", "") or "").strip()
    number = str(_field(leg, "flight_number", "") or "").strip()
    return " ".join(part for part in (airline, number) if part) or "Flight"


def _kind_label(leg: Any, language: str) -> str:
    if _field(leg, "is_layover"):
        return "Nối chuyến" if language == "vi" else "Connecting"
    return "Bay thẳng" if language == "vi" else "Direct"


def _leg_route_line(leg: Any, language: str, prefix: str = "") -> str:
    dep_time = _field(leg, "departure_time", "") or ""
    arr_time = _field(leg, "arrival_time", "") or ""
    dep = _airport_code(_field(leg, "departure_airport", ""))
    arr = _airport_code(_field(leg, "arrival_airport", ""))
    duration = _duration(_field(leg, "duration_minutes", 0))
    bits = [part for part in (duration, _kind_label(leg, language)) if part]
    route = f"**{dep_time}** {dep} → **{arr_time}** {arr}"
    if bits:
        route = f"{route} · {' · '.join(bits)}"
    return f"{prefix}{route}" if prefix else route


def _layover_line(leg: Any, language: str) -> str:
    if not _field(leg, "is_layover"):
        return ""
    stop = _airport_short(_field(leg, "layover_airport", ""))
    wait = _duration(_field(leg, "layover_duration_minutes", 0))
    if language == "vi":
        label = f"Dừng {stop}" if stop else "Có điểm dừng"
    else:
        label = f"Layover {stop}" if stop else "Has a layover"
    return f"{label} {wait}".strip()


def _photo_url(url: Any) -> str:
    text = str(url or "").strip()
    if not text or text.lower() in ("none", "null"):
        return ""
    return (
        text.replace("square60", "max500")
        .replace("square90", "max500")
        .replace("square200", "max500")
    )


def _maps_url(name: str) -> str:
    query = quote_plus((name or "").strip())
    if not query:
        return ""
    return f"https://www.google.com/maps/search/?api=1&query={query}"


def format_flight_options_markdown(
    flights: Optional[List[Any]],
    language: Optional[str] = "en",
    limit: int = 10,
    origin: Optional[str] = None,
    destination: Optional[str] = None,
    heading: bool = True,
) -> str:
    if not flights:
        return ""
    lang = _lang(language)
    shown = list(flights[:limit])
    lines: List[str] = []
    if heading:
        route = " → ".join(part for part in (origin, destination) if part)
        if lang == "vi":
            title = f"**Chuyến bay {route}**" if route else "**Chuyến bay từ Booking.com**"
            lines.append(title)
            lines.append(f"*{len(shown)} lựa chọn từ Booking.com*")
        else:
            title = f"**Flights {route}**" if route else "**Flights from Booking.com**"
            lines.append(title)
            lines.append(f"*{len(shown)} options from Booking.com*")
        lines.append("")
    go_label = "Đi: " if lang == "vi" else "Outbound: "
    return_label = "Về: " if lang == "vi" else "Return: "
    for index, item in enumerate(shown, 1):
        dep = _field(item, "departure_leg")
        ret = _field(item, "return_leg")
        price = _price_text(_field(item, "price", 0) or 0)
        lines.append(f"{index}. **{_carrier(dep)}** · **{price}**")
        if dep:
            prefix = go_label if ret else ""
            lines.append(f"   - {_leg_route_line(dep, lang, prefix)}")
            layover = _layover_line(dep, lang)
            if layover:
                lines.append(f"   - {layover}")
        if ret:
            lines.append(f"   - {_leg_route_line(ret, lang, return_label)}")
            layover = _layover_line(ret, lang)
            if layover:
                lines.append(f"   - {layover}")
    return "\n".join(lines).strip()


def compact_flight_digest(flights: Optional[List[Any]], limit: int = 8) -> str:
    if not flights:
        return ""
    lines = [f"Booking.com flight options ({min(len(flights), limit)}):"]
    for index, item in enumerate(flights[:limit], 1):
        dep = _field(item, "departure_leg") or {}
        airline = _field(dep, "airline", "") or "Unknown"
        number = _field(dep, "flight_number", "") or ""
        dep_air = _airport_code(_field(dep, "departure_airport", ""))
        arr_air = _airport_code(_field(dep, "arrival_airport", ""))
        price = _price_text(_field(item, "price", 0) or 0)
        lines.append(f"{index}. {airline} {number} {dep_air} → {arr_air} {price}")
    return "\n".join(lines)


def format_hotel_options_markdown(
    hotels: Optional[List[Any]],
    language: Optional[str] = "en",
    limit: int = 8,
    destination: Optional[str] = None,
    heading: bool = True,
    include_photos: bool = True,
    nights: Optional[int] = None,
    assumed_checkout: bool = False,
) -> str:
    if not hotels:
        return ""
    lang = _lang(language)
    shown = list(hotels[:limit])
    stay_nights = nights if nights and nights > 0 else 1
    lines: List[str] = []
    if heading:
        if lang == "vi":
            title = f"**Khách sạn tại {destination}**" if destination else "**Khách sạn**"
            if assumed_checkout:
                count = f"*{len(shown)} lựa chọn từ Booking.com · giá mẫu {stay_nights} đêm (chưa có ngày trả phòng)*"
            else:
                count = f"*{len(shown)} lựa chọn từ Booking.com · {stay_nights} đêm*"
        else:
            title = f"**Hotels in {destination}**" if destination else "**Hotels**"
            night_word = "night" if stay_nights == 1 else "nights"
            if assumed_checkout:
                count = f"*{len(shown)} options from Booking.com · sample {stay_nights} {night_word} (no checkout yet)*"
            else:
                count = f"*{len(shown)} options from Booking.com · {stay_nights} {night_word}*"
        lines.extend([title, count, ""])
    night = "/ đêm" if lang == "vi" else "/ night"
    if assumed_checkout:
        stay = f"{stay_nights} đêm mẫu" if lang == "vi" else f"sample {stay_nights}n"
    elif lang == "vi":
        stay = f"cả {stay_nights} đêm" if stay_nights != 1 else "cả kỳ nghỉ"
    else:
        stay = f"{stay_nights}n stay" if stay_nights != 1 else "total stay"
    reviews = "đánh giá" if lang == "vi" else "reviews"
    map_label = "Bản đồ" if lang == "vi" else "Map"
    for index, item in enumerate(shown, 1):
        name = str(_field(item, "hotel_name", "") or "Hotel").strip()
        total = _price_text(_field(item, "total_price", 0) or 0)
        per_night = _field(item, "price_per_night", None)
        rating = _field(item, "rating", "")
        word = str(_field(item, "rating_word", "") or "").strip()
        count_reviews = _field(item, "review_count", None)
        photo = _photo_url(_field(item, "main_photo_url", "")) if include_photos else ""
        lines.append(f"{index}. **{name}** · **{total}** ({stay})")
        if photo:
            lines.append(f"   ![{name}]({photo})")
        detail_bits = []
        if rating not in (None, ""):
            try:
                detail_bits.append(f"**{float(rating):.1f}/10**")
            except (TypeError, ValueError):
                detail_bits.append(f"**{rating}/10**")
        if word:
            detail_bits.append(word)
        if count_reviews not in (None, ""):
            try:
                detail_bits.append(f"{int(count_reviews):,} {reviews}")
            except (TypeError, ValueError):
                detail_bits.append(f"{count_reviews} {reviews}")
        if detail_bits:
            lines.append(f"   - {' · '.join(detail_bits)}")
        if per_night not in (None, ""):
            lines.append(f"   - {_price_text(per_night)} {night}")
        maps = _maps_url(name)
        if maps:
            lines.append(f"   - [{map_label}]({maps})")
    return "\n".join(lines).strip()


def format_event_options_markdown(
    events: Optional[List[Any]],
    language: Optional[str] = "en",
    limit: int = 10,
    destination: Optional[str] = None,
    heading: bool = True,
) -> str:
    if not events:
        return ""
    lang = _lang(language)
    shown = list(events[:limit])
    lines: List[str] = []
    if heading:
        if lang == "vi":
            title = f"**Sự kiện tại {destination}**" if destination else "**Sự kiện**"
            lines.extend([title, f"*{len(shown)} sự kiện*", ""])
        else:
            title = f"**Events in {destination}**" if destination else "**Events**"
            lines.extend([title, f"*{len(shown)} events*", ""])
    link_label = "Chi tiết / vé" if lang == "vi" else "Details / tickets"
    venue_label = "Địa điểm" if lang == "vi" else "Venue"
    date_label = "Ngày" if lang == "vi" else "Date"
    for index, item in enumerate(shown, 1):
        name = str(_field(item, "name", "") or "Event").strip()
        date = str(_field(item, "date", "") or "").strip()
        venue = str(_field(item, "venue", "") or "").strip()
        url = str(_field(item, "url", "") or "").strip()
        lines.append(f"{index}. **{name}**")
        if date:
            lines.append(f"   - {date_label}: {date}")
        if venue:
            lines.append(f"   - {venue_label}: {venue}")
        if url and url != "#":
            lines.append(f"   - [{link_label}]({url})")
    return "\n".join(lines).strip()


def format_activity_options_markdown(
    raw: Optional[str],
    language: Optional[str] = "en",
    limit: int = 8,
    destination: Optional[str] = None,
    heading: bool = True,
) -> str:
    text = (raw or "").strip()
    if not text or "No relevant activities found" in text:
        return ""
    lang = _lang(language)
    if lang == "vi":
        title = f"**Gợi ý vui chơi tại {destination}**" if destination else "**Gợi ý vui chơi**"
    else:
        title = f"**Things to do in {destination}**" if destination else "**Things to do**"
    titles = re.findall(r"Title:\s*(.+)", text)
    contents = re.findall(r"Content:\s*(.+)", text)
    items: List[tuple[str, str]] = []
    if titles:
        for index, name in enumerate(titles[:limit]):
            snippet = contents[index].strip() if index < len(contents) else ""
            items.append((name.strip(), sanitize_reply(snippet, max_chars=220)))
    else:
        for line in text.splitlines():
            cleaned = re.sub(r"^\s*(?:\d+[\.\)]\s+|[-*]\s+)", "", line).strip()
            if len(cleaned) >= 8:
                items.append((cleaned[:120], ""))
            if len(items) >= limit:
                break
    if not items:
        body = sanitize_reply(text, max_chars=3500)
        return f"{title}\n\n{body}" if heading else body
    lines: List[str] = []
    if heading:
        count = f"*{len(items)} gợi ý*" if lang == "vi" else f"*{len(items)} ideas*"
        lines.extend([title, count, ""])
    for index, (name, snippet) in enumerate(items, 1):
        lines.append(f"{index}. **{name}**")
        if snippet:
            lines.append(f"   - {snippet}")
    return "\n".join(lines).strip()


def lookup_intro(language: str, targets: List[str]) -> str:
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
        return f"Mình tìm được {joined} từ dữ liệu thật:"
    labels = {
        "flight": "flights",
        "hotel": "hotels",
        "event": "events",
        "activity": "places to visit",
    }
    named = [labels[item] for item in targets if item in labels]
    joined = ", ".join(named) if named else "results"
    return f"Here are live {joined} I found:"


def lookup_footer(language: str, targets: List[str]) -> str:
    lang = _lang(language)
    if lang == "vi":
        if targets == ["flight"]:
            return "Bạn chọn **số mấy**, hay mình lọc **bay thẳng** / **rẻ nhất** giúp bạn?"
        if targets == ["hotel"]:
            return (
                "Bạn chọn **số mấy**, lọc theo **giá** / **đánh giá**, "
                "hoặc cho **ngày trả phòng** để mình tính lại cả kỳ nghỉ."
            )
        if targets == ["event"]:
            return "Bạn muốn sự kiện nào, hoặc mình lọc theo ngày giúp bạn?"
        if targets == ["activity"]:
            return "Bạn muốn mình kể kỹ địa điểm nào?"
        return "Bạn muốn chọn mục nào, hoặc mình lọc lại theo giá / thời gian?"
    if targets == ["flight"]:
        return "Reply with a **number**, or ask for **direct** or **cheapest**."
        if targets == ["hotel"]:
            return (
                "Reply with a **number**, ask me to sort by **price** or **rating**, "
                "or send a **checkout date** to price the full stay."
            )
    if targets == ["event"]:
        return "Tell me which event you want, or ask me to filter by date."
    if targets == ["activity"]:
        return "Tell me which place you want more detail on."
    return "Tell me which option you want, or ask me to filter by price or time."


def compose_lookup_reply(sections: List[str], language: str, targets: List[str]) -> str:
    if not sections:
        return ""
    body = "\n\n".join(section for section in sections if section)
    if len(sections) > 1:
        body = f"{lookup_intro(language, targets)}\n\n{body}"
    return f"{body}\n\n{lookup_footer(language, targets)}"


def polish_chat_markdown(text: str) -> str:
    """Keep chat/recall answers readable even when the model writes a wall of text."""
    cleaned = (text or "").strip()
    if not cleaned:
        return cleaned
    if looks_like_option_list(cleaned):
        return cleaned
    jammed = re.sub(r"(?<!\n)\s+(\d+\.\s+)", r"\n\n\1", cleaned)
    if looks_like_option_list(jammed):
        cleaned = jammed
    cleaned = re.sub(r"\s+[•●]\s+", "\n- ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
