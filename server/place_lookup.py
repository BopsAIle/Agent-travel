import os
from typing import List, Optional

from langchain_google_genai import ChatGoogleGenerativeAI

from conversation import ChatSession, language_code
from nodes import gemini_api_key, invoke_tool_schema, make_chat_openai
from places import destination_of, extract_place_index, list_itinerary_places, looks_like_place_request, resolve_place
from quality import is_degenerate, sanitize_and_flag, sanitize_reply
from schemas import ConversationTurn, PlaceBrief, PlaceQualityCheck
from telemetry import agent_scope, tracked_invoke, tracked_post

ACTIVITY_SERVICE_URL = os.getenv("ACTIVITY_SERVICE_URL", "http://activity-service:8002")

place_llm = make_chat_openai(max_tokens=1500, temperature=0.2)

critic_llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0,
    google_api_key=gemini_api_key,
)


def _unknown(language: str) -> str:
    return "Chưa rõ" if language == "vi" else "Unknown"


def _clean_field(value: Optional[str], language: str) -> str:
    text, degenerate = sanitize_and_flag(value or "")
    if not text or degenerate:
        return _unknown(language)
    return text


def fetch_place_facts(place_name: str, destination: str) -> str:
    payload = {"place_name": place_name, "destination": destination or ""}
    url = f"{ACTIVITY_SERVICE_URL.rstrip('/')}/place_details"
    try:
        response = tracked_post(url, json=payload, timeout=45)
        response.raise_for_status()
        data = response.json() or {}
    except Exception as exc:
        print(f"-> Place detail service failed: {exc}")
        return ""

    lines: List[str] = []
    for item in data.get("results") or []:
        title = (item.get("title") or "").strip()
        content = (item.get("content") or "").strip()
        source = (item.get("url") or "").strip()
        if not content:
            continue
        block = f"- {title}: {content}"
        if source:
            block += f" (source: {source})"
        lines.append(block)
        if len(lines) >= 5:
            break
    return "\n".join(lines)


def _itinerary_facts(place: Optional[dict], destination: str) -> str:
    if not place:
        return f"Destination city: {destination or 'unknown'}."
    parts = [
        f"Itinerary index: {place.get('index')}",
        f"Name: {place.get('name')}",
        f"City: {destination or 'unknown'}",
    ]
    if place.get("day"):
        parts.append(f"Scheduled day: {place['day']}")
    if place.get("time_of_day"):
        parts.append(f"Suggested time: {place['time_of_day']}")
    if place.get("description"):
        parts.append(f"Itinerary note: {place['description']}")
    if place.get("location"):
        parts.append(f"Listed location: {place['location']}")
    if place.get("maps_url"):
        parts.append(f"Map: {place['maps_url']}")
    return "\n".join(parts)


def generate_place_brief(
    place_name: str,
    destination: str,
    place: Optional[dict],
    web_facts: str,
    language: str,
    critic_notes: Optional[List[str]] = None,
) -> Optional[PlaceBrief]:
    notes = ""
    if critic_notes:
        notes = "Previous draft had issues. Fix them: " + "; ".join(critic_notes)
    prompt = f"""
You write a traveler brief for ONE place. Reply via the PlaceBrief tool only.
Write every field in language '{language}'.
Use only the sources below. If a fact is missing, write Unknown / Chưa rõ. Do not invent hours or prices.
Never repeat a word, phrase, or address fragment. Each fact appears once.

Place: {place_name}
City: {destination or "unknown"}
{notes}

ITINERARY FACTS:
{_itinerary_facts(place, destination)}

WEB SEARCH FACTS:
{web_facts or "(no web results)"}
"""
    try:
        brief = invoke_tool_schema(place_llm, PlaceBrief, prompt, retries=2)
        brief.name = _clean_field(brief.name, language) if brief.name else place_name
        brief.address = _clean_field(brief.address, language)
        brief.why_visit = _clean_field(brief.why_visit, language)
        brief.hours_or_tips = _clean_field(brief.hours_or_tips, language)
        brief.how_to_get_there = _clean_field(brief.how_to_get_there, language)
        brief.good_for = _clean_field(brief.good_for, language)
        cleaned_highlights = []
        for item in brief.highlights or []:
            value = _clean_field(item, language)
            if value and value != _unknown(language) and value not in cleaned_highlights:
                cleaned_highlights.append(value)
            if len(cleaned_highlights) >= 5:
                break
        brief.highlights = cleaned_highlights
        if is_degenerate(" ".join([brief.why_visit, brief.address, " ".join(brief.highlights)])):
            return None
        return brief
    except Exception as exc:
        print(f"-> Place brief generation failed: {exc}")
        return None


def format_place_reply(
    brief: Optional[PlaceBrief],
    place: Optional[dict],
    destination: str,
    language: str,
) -> str:
    if language == "vi":
        labels = {
            "where": "Vị trí",
            "why": "Vì sao nên ghé",
            "highlights": "Nên xem / làm",
            "tips": "Giờ mở cửa / mẹo",
            "go": "Cách đi",
            "good": "Phù hợp",
            "map": "Bản đồ",
            "day": "Trong lịch trình",
        }
    else:
        labels = {
            "where": "Location",
            "why": "Why go",
            "highlights": "Highlights",
            "tips": "Hours / tips",
            "go": "How to get there",
            "good": "Best for",
            "map": "Map",
            "day": "On your itinerary",
        }

    name = (brief.name if brief else None) or (place or {}).get("name") or destination
    lines = [f"**{name}**"]
    if place and place.get("index"):
        day = place.get("day")
        if language == "vi":
            day_bit = f", ngày {day}" if day else ""
            lines.append(f"*{labels['day']}: địa điểm số {place['index']}{day_bit}*")
        else:
            day_bit = f", day {day}" if day else ""
            lines.append(f"*{labels['day']}: stop {place['index']}{day_bit}*")

    address = ""
    if brief and brief.address and brief.address != _unknown(language):
        address = brief.address
    elif place and place.get("location"):
        address = place["location"]
    if address:
        lines.append(f"- **{labels['where']}:** {address}")

    why = brief.why_visit if brief else ""
    if not why or why == _unknown(language):
        why = (place or {}).get("description") or ""
    if why:
        lines.append(f"- **{labels['why']}:** {why}")

    highlights = (brief.highlights if brief else None) or []
    if highlights:
        lines.append(f"- **{labels['highlights']}:**")
        for item in highlights:
            lines.append(f"  - {item}")

    if brief and brief.hours_or_tips and brief.hours_or_tips != _unknown(language):
        lines.append(f"- **{labels['tips']}:** {brief.hours_or_tips}")
    if brief and brief.how_to_get_there and brief.how_to_get_there != _unknown(language):
        lines.append(f"- **{labels['go']}:** {brief.how_to_get_there}")
    if brief and brief.good_for and brief.good_for != _unknown(language):
        lines.append(f"- **{labels['good']}:** {brief.good_for}")

    maps_url = (place or {}).get("maps_url") or ""
    if maps_url:
        lines.append(f"- **{labels['map']}:** {maps_url}")

    return sanitize_reply("\n".join(lines))


def format_fallback_reply(place: Optional[dict], place_name: str, destination: str, language: str) -> str:
    if language == "vi":
        if place:
            day = f" (ngày {place['day']})" if place.get("day") else ""
            desc = place.get("description") or "Địa điểm trong lịch trình của bạn."
            maps = f"\nBản đồ: {place['maps_url']}" if place.get("maps_url") else ""
            return (
                f"**{place.get('name') or place_name}**{day}\n"
                f"{desc}\n"
                f"Mình chưa lấy được mô tả realtime đầy đủ, nhưng đây là thông tin từ lịch trình."
                f"{maps}"
            )
        return (
            f"Mình chưa mô tả được {place_name or 'địa điểm này'} một cách chắc chắn. "
            "Bạn nhắc lại tên địa điểm hoặc số trong lịch trình giúp mình nhé."
        )
    if place:
        day = f" (day {place['day']})" if place.get("day") else ""
        desc = place.get("description") or "This stop is on your itinerary."
        maps = f"\nMap: {place['maps_url']}" if place.get("maps_url") else ""
        return (
            f"**{place.get('name') or place_name}**{day}\n"
            f"{desc}\n"
            f"I could not fetch a full live briefing, so this is what we already have on the itinerary."
            f"{maps}"
        )
    return (
        f"I could not put together a reliable briefing for {place_name or 'that place'}. "
        "Please tell me the place name or its number on the itinerary."
    )


def critique_reply(
    user_message: str,
    place_name: str,
    web_facts: str,
    draft: str,
    language: str,
) -> Optional[PlaceQualityCheck]:
    prompt = f"""
You are a quality critic for a travel-agent answer.
Approve only if the draft is useful, about the right place, and not repetitive.

Fail if:
- A phrase or token repeats (e.g. "2-nd floor," many times)
- It describes the wrong place
- It invents precise hours/prices not in the sources
- It is empty, truncated, or mostly markdown noise

User asked: {user_message}
Place: {place_name}
Sources:
{web_facts or "(itinerary only)"}
Draft:
{draft[:2500]}
Language expected: {language}
"""
    if is_degenerate(draft):
        return PlaceQualityCheck(ok=False, verdict="fallback", issues=["repetition loop"])
    bound = critic_llm.bind_tools([PlaceQualityCheck])
    try:
        with agent_scope("quality_critic"):
            message = tracked_invoke(
                bound,
                prompt,
                model="gemini-2.5-flash",
                provider="google",
            )
        if message.tool_calls:
            return PlaceQualityCheck(**message.tool_calls[0]["args"])
    except Exception as exc:
        print(f"-> Place critic failed: {exc}")
    return None


def _replace_last_assistant(session: ChatSession, content: str) -> None:
    for item in reversed(session.messages or []):
        if item.get("role") == "assistant":
            item["content"] = content
            return
    session.messages.append({"role": "assistant", "content": content})


def degenerate_chat_fallback(language: str) -> str:
    if language_code(language) == "vi":
        return "Mình bị lỗi khi soạn câu trả lời. Bạn hỏi lại tên địa điểm hoặc số trong lịch trình giúp mình nhé."
    return "I had trouble writing that answer. Could you ask again with the place name or its number on the itinerary?"


def fulfill_place_request(session: ChatSession, turn: ConversationTurn, user_message: str) -> str:
    language = language_code(turn.detected_language or session.language)
    destination = destination_of(session.trip_state) or (session.slots or {}).get("destination") or ""
    places = list_itinerary_places(session.trip_state)
    index = turn.place_index or extract_place_index(user_message)
    if index and places and not (1 <= index <= len(places)):
        if language == "vi":
            return f"Lịch trình hiện có {len(places)} địa điểm (số 1–{len(places)}). Bạn chọn lại số giúp mình nhé."
        return f"The itinerary has {len(places)} places (1–{len(places)}). Could you pick another number?"
    if index and not places:
        if language == "vi":
            return "Mình chưa có lịch trình để đối chiếu địa điểm theo số. Bạn nói tên địa điểm, hoặc tạo lịch trình trước nhé."
        return "I do not have a numbered itinerary yet. Tell me the place name, or generate a plan first."

    place = resolve_place(session.trip_state, turn.place_index, turn.place_query, user_message)
    place_name = (
        (place or {}).get("name")
        or (turn.place_query or "").strip()
        or user_message.strip()
    )
    if not (place or turn.place_query or destination):
        return format_fallback_reply(None, place_name, destination, language)

    with agent_scope("place_lookup"):
        web_facts = fetch_place_facts(place_name, destination)
        brief = generate_place_brief(place_name, destination, place, web_facts, language)
        draft = format_place_reply(brief, place, destination, language)
        draft, bad = sanitize_and_flag(draft)
        if not draft.strip() or bad:
            draft = format_fallback_reply(place, place_name, destination, language)

        check = critique_reply(user_message, place_name, web_facts, draft, language)
        if check and check.verdict == "retry":
            brief = generate_place_brief(
                place_name,
                destination,
                place,
                web_facts,
                language,
                critic_notes=check.issues,
            )
            draft = format_place_reply(brief, place, destination, language)
            draft, bad = sanitize_and_flag(draft)
            if bad or not draft.strip():
                draft = format_fallback_reply(place, place_name, destination, language)
        elif check and check.verdict == "fallback":
            draft = format_fallback_reply(place, place_name, destination, language)

    return sanitize_reply(draft)


def should_fulfill_place(session: ChatSession, turn: ConversationTurn, user_message: str) -> bool:
    if turn.intent == "place":
        return True
    if resolve_place(session.trip_state, turn.place_index, turn.place_query, user_message):
        return True
    return looks_like_place_request(user_message)


def apply_place_or_quality_gate(session: ChatSession, turn: ConversationTurn, user_message: str) -> ConversationTurn:
    if should_fulfill_place(session, turn, user_message):
        turn.intent = "place"
        turn.ready_to_plan = False
        turn.reply = fulfill_place_request(session, turn, user_message)
        _replace_last_assistant(session, turn.reply)
        return turn

    cleaned, bad = sanitize_and_flag(turn.reply or "")
    if bad:
        turn.reply = degenerate_chat_fallback(session.language)
        _replace_last_assistant(session, turn.reply)
    elif cleaned != (turn.reply or ""):
        turn.reply = cleaned
        _replace_last_assistant(session, turn.reply)
    return turn
