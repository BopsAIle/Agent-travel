from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from langchain_groq import ChatGroq

from nodes import groq_api_key, invoke_tool_schema, llm
from places import catalog_text, list_itinerary_places, looks_like_place_request
from quality import sanitize_and_flag, sanitize_reply
from telemetry import agent_scope, tracked_invoke
from schemas import (
    REQUIRED_TRIP_FIELDS,
    ConversationTurn,
    PartialTripRequest,
    TripRequest,
)


ALL_REFRESH = ["flight", "hotel", "event", "activities"]
STRUCTURAL_SLOT_KEYS = ("origin", "destination", "start_date", "end_date", "person")

FIELD_LABELS = {
    "en": {
        "origin": "departure city",
        "destination": "destination",
        "start_date": "start date",
        "end_date": "end date",
        "person": "number of travelers",
    },
    "vi": {
        "origin": "điểm đi",
        "destination": "điểm đến",
        "start_date": "ngày bắt đầu",
        "end_date": "ngày kết thúc",
        "person": "số người",
    },
}

MISSING_PROMPT = {
    "en": "I still need {fields} before I can plan the trip. Could you share that?",
    "vi": "Mình còn thiếu {fields} để lên kế hoạch. Bạn cho mình biết thêm được không?",
}

chat_llm = ChatGroq(
    model="openai/gpt-oss-120b",
    api_key=groq_api_key,
    max_retries=2,
    temperature=0.3,
    max_tokens=1024,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def session_title(slots: dict, messages: List[dict]) -> str:
    origin = (slots or {}).get("origin")
    destination = (slots or {}).get("destination")
    if origin and destination:
        return f"{origin} → {destination}"
    for item in messages or []:
        if item.get("role") == "user" and item.get("content"):
            text = str(item["content"]).strip().replace("\n", " ")
            if len(text) > 48:
                return text[:48].rstrip() + "…"
            return text
    return "New chat"


@dataclass
class ChatSession:
    session_id: str
    user_id: Optional[str] = None
    messages: List[dict] = field(default_factory=list)
    slots: dict = field(default_factory=dict)
    language: Optional[str] = None
    trip_state: Optional[dict] = None
    user_feedback: Optional[str] = None
    has_plan: bool = False
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    markdown_report: Optional[str] = None


def session_summary(session: ChatSession) -> dict:
    preview = ""
    for item in reversed(session.messages or []):
        if item.get("role") in ("user", "assistant") and item.get("content"):
            preview = str(item["content"]).strip().replace("\n", " ")
            break
    return {
        "session_id": session.session_id,
        "title": session_title(session.slots, session.messages),
        "updated_at": session.updated_at,
        "created_at": session.created_at,
        "preview": preview[:80],
        "has_plan": session.has_plan,
        "slots": slots_snapshot(session.slots) if session.slots else {},
    }


def language_code(value: Optional[str]) -> str:
    if not value:
        return "en"
    code = value.strip().lower().replace("_", "-")
    if "-" in code:
        code = code.split("-", 1)[0]
    return code or "en"


def missing_required(slots: dict) -> List[str]:
    missing = []
    for key in REQUIRED_TRIP_FIELDS:
        value = slots.get(key)
        if value is None or value == "":
            missing.append(key)
        elif key == "person" and (not isinstance(value, int) or value <= 0):
            try:
                if int(value) <= 0:
                    missing.append(key)
            except (TypeError, ValueError):
                missing.append(key)
    return missing


def merge_slots(existing: dict, extracted: PartialTripRequest) -> dict:
    merged = dict(existing)
    updates = extracted.model_dump(exclude_none=True)
    for key, value in updates.items():
        if value == "" or value == []:
            continue
        merged[key] = value
    return merged


def slots_snapshot(slots: dict) -> dict:
    return {
        "origin": slots.get("origin"),
        "destination": slots.get("destination"),
        "start_date": slots.get("start_date"),
        "end_date": slots.get("end_date"),
        "person": slots.get("person"),
        "budget": slots.get("budget"),
        "interests": slots.get("interests"),
        "daily_spending_budget": slots.get("daily_spending_budget"),
    }


def trip_request_from_slots(slots: dict) -> TripRequest:
    payload = dict(slots)
    if payload.get("person") is not None:
        payload["person"] = int(payload["person"])
    return TripRequest(**payload)


def structural_fields_changed(previous: dict, current: dict) -> bool:
    for key in STRUCTURAL_SLOT_KEYS:
        if previous.get(key) != current.get(key):
            return True
    return False

## Xác định các thành phần thay đổi trong lịch trình
def determine_refresh(
    previous_slots: dict,
    current_slots: dict,
    intent: str,
    refine_targets: List[str],
    has_plan: bool,
) -> List[str]:
    if not has_plan or intent == "plan":
        return list(ALL_REFRESH)

    targets = set(refine_targets or [])
    if (
        structural_fields_changed(previous_slots, current_slots)
        or "full" in targets
        or "dates" in targets
        or "destination" in targets
    ):
        return list(ALL_REFRESH)

    refresh: List[str] = []
    if "flight" in targets:
        refresh.append("flight")
    if "hotel" in targets:
        refresh.append("hotel")
    if "activities" in targets:
        refresh.extend(["event", "activities"])
    if "budget" in targets:
        refresh.extend(["flight", "hotel"])

    if not refresh:
        refresh = ["hotel"]
    seen = set()
    ordered = []
    for item in refresh:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def synthesize_user_request(
    slots: dict,
    last_message: str,
    feedback: Optional[str] = None,
    memory_context: Optional[str] = None,
) -> str:
    parts = []
    origin = slots.get("origin")
    destination = slots.get("destination")
    if origin and destination:
        parts.append(f"Plan a trip from {origin} to {destination}.")
    if slots.get("start_date") and slots.get("end_date"):
        parts.append(f"Dates: {slots['start_date']} to {slots['end_date']}.")
    if slots.get("person"):
        parts.append(f"Number of people: {slots['person']}.")
    if slots.get("budget") is not None:
        parts.append(f"Budget: {slots['budget']}.")
    if slots.get("interests"):
        interests = slots["interests"]
        if isinstance(interests, list):
            interests = ", ".join(interests)
        parts.append(f"Interests: {interests}.")
    if slots.get("daily_spending_budget") is not None:
        parts.append(f"Daily spending budget per person: {slots['daily_spending_budget']}.")
    if last_message:
        parts.append(f"Latest request: {last_message}")
    if feedback:
        parts.append(f"User feedback: {feedback}")
    if memory_context:
        parts.append(f"Traveler long-term preferences: {memory_context}")
    return " ".join(parts) if parts else last_message


def build_graph_state(
    session: ChatSession,
    refresh: List[str],
    user_request: str,
    memory_context: Optional[str] = None,
) -> dict:
    prev = session.trip_state or {}
    previous_slots = {}
    prev_plan = prev.get("trip_plan")
    if prev_plan is not None:
        previous_slots = (
            prev_plan.model_dump() if hasattr(prev_plan, "model_dump") else dict(prev_plan)
        )

    plan = trip_request_from_slots(session.slots)
    clear_search = (
        not prev
        or structural_fields_changed(previous_slots, session.slots)
        or set(refresh) >= set(ALL_REFRESH)
    )

    state = {
        "user_request": user_request,
        "trip_plan": plan,
        "refresh": refresh,
        "language": session.language or "en",
        "user_feedback": session.user_feedback,
        "refinement_count": 0,
        "selected_flight": prev.get("selected_flight"),
        "flight_options": list(prev.get("flight_options") or []),
        "selected_hotel": prev.get("selected_hotel"),
        "hotel_options": list(prev.get("hotel_options") or []),
        "extracted_activities": prev.get("extracted_activities"),
        "events": prev.get("events"),
        "final_itinerary": prev.get("final_itinerary"),
        "evaluation_result": prev.get("evaluation_result"),
        "map_html": prev.get("map_html"),
        "markdown_report": prev.get("markdown_report"),
        "user_id": session.user_id,
        "memory_context": memory_context or "",
    }

    if clear_search:
        state.update(
            {
                "selected_flight": None,
                "flight_options": [],
                "selected_hotel": None,
                "hotel_options": [],
                "extracted_activities": None,
                "events": None,
                "final_itinerary": None,
                "evaluation_result": None,
                "map_html": None,
                "markdown_report": None,
            }
        )
    else:
        if "activities" in refresh:
            state["extracted_activities"] = None
        if "event" in refresh:
            state["events"] = None
        if "flight" in refresh and "hotel" not in refresh:
            pass
    return state


def _missing_question(language: str, missing: List[str]) -> str:
    lang = language if language in MISSING_PROMPT else "en"
    labels = FIELD_LABELS.get(lang, FIELD_LABELS["en"])
    named = [labels.get(item, item) for item in missing]
    if lang == "vi":
        joined = ", ".join(named)
    elif len(named) == 1:
        joined = named[0]
    elif len(named) == 2:
        joined = f"{named[0]} and {named[1]}"
    else:
        joined = ", ".join(named[:-1]) + f", and {named[-1]}"
    return MISSING_PROMPT[lang].format(fields=joined)


def _history_text(messages: List[dict], limit: int = 16) -> str:
    lines = []
    for item in messages[-limit:]:
        role = item.get("role", "user")
        content = sanitize_reply(str(item.get("content") or ""), max_chars=1200)
        lines.append(f"{role}: {content}")
    return "\n".join(lines) if lines else "(no prior messages)"


def _itinerary_digest(trip_state: Optional[dict]) -> str:
    if not trip_state:
        return "No itinerary has been generated yet."
    plan = trip_state.get("trip_plan")
    flight = trip_state.get("selected_flight")
    hotel = trip_state.get("selected_hotel")
    evaluation = trip_state.get("evaluation_result")
    parts = []
    if plan:
        dest = plan.destination if hasattr(plan, "destination") else plan.get("destination")
        start = plan.start_date if hasattr(plan, "start_date") else plan.get("start_date")
        end = plan.end_date if hasattr(plan, "end_date") else plan.get("end_date")
        parts.append(f"Current plan: {dest} from {start} to {end}.")
    if hotel:
        name = hotel.hotel_name if hasattr(hotel, "hotel_name") else hotel.get("hotel_name")
        price = hotel.total_price if hasattr(hotel, "total_price") else hotel.get("total_price")
        parts.append(f"Hotel: {name} (€{price}).")
    if flight:
        price = flight.price if hasattr(flight, "price") else flight.get("price")
        airline = None
        if hasattr(flight, "departure_leg"):
            airline = flight.departure_leg.airline
        elif isinstance(flight, dict):
            airline = (flight.get("departure_leg") or {}).get("airline")
        parts.append(f"Flight: {airline or 'selected'} (€{price}).")
    if evaluation:
        total = evaluation.total_cost if hasattr(evaluation, "total_cost") else evaluation.get("total_cost")
        parts.append(f"Estimated total: €{total}.")
    places = list_itinerary_places(trip_state)
    if places:
        parts.append("Numbered itinerary places:\n" + catalog_text(places))
    return " ".join(parts) if parts else "No itinerary has been generated yet."


def run_conversation_turn(
    session: ChatSession,
    user_message: str,
    memory_block: str = "",
) -> tuple[ConversationTurn, dict]:
    session.messages.append({"role": "user", "content": user_message})
    previous_slots = dict(session.slots)
    memory_section = (
        f"\nTraveler memory (use this; do not invent facts the user did not store):\n{memory_block}\n"
        if memory_block
        else "\nNo long-term memory retrieved for this traveler yet.\n"
    )

    prompt = f"""
You are a friendly AI travel agent chatting with one traveler.
Reply in the SAME language as the user's latest message. Detect that language.
Today's date is {datetime.now().strftime('%Y-%m-%d')}. Convert relative dates (next weekend, in 2 weeks) to YYYY-MM-DD.
{memory_section}
Goals:
- Collect trip details naturally. Ask at most 1-2 missing questions per turn. Never present a form.
- Fill origin, destination, start_date, end_date, person, budget, interests, daily_spending_budget only when the user mentioned them this turn. Otherwise leave them unset.
- Required before planning: origin, destination, start_date, end_date, person.
- Optional: budget, interests, daily_spending_budget. You may ask for them but do not block forever.
- If the user provided a complete trip request, set intent=plan and ready_to_plan=true. Confirm briefly; the system will start planning.
- If an itinerary already exists and the user wants changes (cheaper hotel, different dates, more museums), set intent=refine and fill refine_targets.
- If the user asks about previous trips, preferences, or "last time", set intent=recall and answer from traveler memory. Do not start a new plan unless they asked for one.
- If the user asks for details about a numbered stop ("địa điểm số 5", "location 5") or a named attraction, set intent=place. Fill place_index and/or place_query. Reply with ONE short sentence only. Do not describe the place in this reply.
- Otherwise intent=chat.
- ready_to_plan=true only when required fields are known (already stored or extracted now) AND the user wants a plan or gave a complete request.
- You may reuse the traveler's home city or standing preferences from memory when they omit origin or hotel style, but still confirm if unsure.
- Never repeat a phrase. If you are unsure of an address, say so once.

Known slots so far: {session.slots or "{}"}
Existing itinerary: {_itinerary_digest(session.trip_state)}
Has a generated plan: {session.has_plan}

Conversation:
{_history_text(session.messages)}
"""

    try:
        with agent_scope("conversation"):
            turn = invoke_tool_schema(chat_llm, ConversationTurn, prompt)
    except Exception as exc:
        print(f"-> Conversation agent failed: {exc}")
        lang = session.language or "en"
        fallback_reply = (
            "Mình chưa nghe rõ. Bạn nói lại điểm đi, điểm đến và ngày đi được không?"
            if lang == "vi"
            else "I didn't quite catch that. Could you tell me where you're traveling from, where to, and when?"
        )
        turn = ConversationTurn(
            reply=fallback_reply,
            detected_language=lang,
            intent="chat",
            ready_to_plan=False,
        )

    session.language = language_code(turn.detected_language or session.language)
    session.slots = merge_slots(session.slots, turn.to_extracted())
    missing = missing_required(session.slots)

    if looks_like_place_request(user_message) or turn.intent == "place":
        turn.intent = "place"
        turn.ready_to_plan = False

    if turn.intent in ("recall", "place"):
        turn.ready_to_plan = False
    elif missing and turn.intent in ("plan", "refine"):
        turn.intent = "chat"
        turn.ready_to_plan = False
        turn.reply = _missing_question(session.language, missing)
    elif missing:
        turn.ready_to_plan = False
    elif turn.ready_to_plan and turn.intent == "chat":
        turn.intent = "plan"

    if turn.intent == "refine" and not session.has_plan:
        turn.intent = "plan" if not missing else "chat"
        if missing:
            turn.reply = _missing_question(session.language, missing)

    if turn.intent in ("plan", "refine"):
        session.user_feedback = user_message
    else:
        session.user_feedback = None

    cleaned, _bad = sanitize_and_flag(turn.reply or "")
    turn.reply = cleaned
    session.messages.append({"role": "assistant", "content": turn.reply})
    turn.detected_language = session.language
    return turn, previous_slots


def should_run_planner(turn: ConversationTurn, session: ChatSession) -> bool:
    if turn.intent in ("recall", "place"):
        return False
    if missing_required(session.slots):
        return False
    if turn.intent in ("plan", "refine"):
        return True
    return bool(turn.ready_to_plan)


def summarize_completed_plan(language: str, trip_state: dict) -> str:
    lang = language_code(language)
    plan = trip_state.get("trip_plan")
    hotel = trip_state.get("selected_hotel")
    flight = trip_state.get("selected_flight")
    evaluation = trip_state.get("evaluation_result")
    itinerary = trip_state.get("final_itinerary")

    if not itinerary or not plan:
        if lang == "vi":
            return "Mình chưa tạo được lịch trình đầy đủ. Bạn thử đổi ngày, ngân sách hoặc nói rõ hơn được không?"
        return "I couldn't put together a complete itinerary. Could you try different dates, a different budget, or a bit more detail?"

    dest = plan.destination
    start = plan.start_date
    end = plan.end_date
    hotel_name = hotel.hotel_name if hotel else ""
    airline = ""
    if flight and getattr(flight, "departure_leg", None):
        airline = flight.departure_leg.airline
    total = evaluation.total_cost if evaluation else None

    facts = (
        f"Destination: {dest}. Dates: {start} to {end}. "
        f"Hotel: {hotel_name}. Flight: {airline}. "
        f"Estimated total: {total}."
    )
    prompt = (
        f"Write 3 short sentences summarizing this trip for the traveler, in language '{lang}'. "
        f"Invite them to ask for changes (hotel, flights, dates, activities). No markdown.\n{facts}"
    )
    try:
        with agent_scope("conversation"):
            message = tracked_invoke(llm, prompt, model="openai/gpt-oss-120b", provider="groq")
        content = getattr(message, "content", None)
        if isinstance(content, str) and content.strip():
            return content.strip()
    except Exception as exc:
        print(f"-> Plan summary LLM failed: {exc}")

    if lang == "vi":
        cost = f" Tổng ước tính khoảng €{total:,.0f}." if total is not None else ""
        return (
            f"Lịch trình {dest} từ {start} đến {end} đã sẵn sàng"
            f"{f', khách sạn {hotel_name}' if hotel_name else ''}"
            f"{f', bay {airline}' if airline else ''}.{cost} "
            "Bạn muốn chỉnh khách sạn, vé máy bay hay lịch trình thì cứ nói nhé."
        )
    cost = f" Estimated total is about €{total:,.0f}." if total is not None else ""
    return (
        f"Your itinerary for {dest} ({start} to {end}) is ready"
        f"{f', staying at {hotel_name}' if hotel_name else ''}"
        f"{f', flying {airline}' if airline else ''}.{cost} "
        "Tell me if you want to change the hotel, flights, dates, or activities."
    )
