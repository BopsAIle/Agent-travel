from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from conversation import (
    ChatSession,
    chat_llm,
    run_conversation_turn,
    should_run_planner,
)
from flight_display import attach_booking_flights_if_requested
from memory.manager import (
    MemoryBundle,
    persist_working,
    retrieve_memory,
    write_episode_from_plan,
    write_semantic_from_turn,
)
from nodes import invoke_tool_schema
from place_lookup import apply_place_or_quality_gate
from schemas import ConversationTurn, MemoryExtraction
from telemetry import agent_scope


@dataclass
class SupervisorResult:
    turn: ConversationTurn
    previous_slots: dict
    bundle: MemoryBundle
    should_plan: bool
    route: str


def _extract_semantic_memory(session: ChatSession, user_message: str) -> Optional[MemoryExtraction]:
    prompt = f"""
You extract LONG-TERM traveler memory, not the current trip's dates or one-off destinations.

Store only durable preferences and constraints:
- home city, typical budget, hotel style, dietary needs, standing interests, travel pace, language
- facts like allergies, "hates overnight flights", "travels with kids"

Do NOT store:
- this trip's start/end dates unless the user said they always travel in that season
- a destination they want only this time

If nothing durable was said, return empty facts and no profile fields.

Known profile slots already on this trip (ignore unless they sound like lasting preferences): {session.slots or "{}"}
User message: {user_message}
"""
    try:
        return invoke_tool_schema(chat_llm, MemoryExtraction, prompt)
    except Exception as exc:
        print(f"-> Memory extraction failed: {exc}")
        return None


def run_supervised_turn(
    db: Session,
    session: ChatSession,
    user_message: str,
) -> SupervisorResult:
    with agent_scope("memory"):
        bundle = retrieve_memory(db, session.user_id, user_message)
    turn, previous_slots = run_conversation_turn(
        session,
        user_message,
        memory_block=bundle.as_prompt(),
    )
    turn = apply_place_or_quality_gate(session, turn, user_message)
    turn = attach_booking_flights_if_requested(session, turn, user_message)
    route = turn.intent if turn.intent in ("chat", "plan", "refine", "recall", "place") else "chat"
    with agent_scope("memory"):
        extraction = _extract_semantic_memory(session, user_message)
        write_semantic_from_turn(db, session, extraction)
        persist_working(db, session)
    return SupervisorResult(
        turn=turn,
        previous_slots=previous_slots,
        bundle=bundle,
        should_plan=should_run_planner(turn, session),
        route=route,
    )


def after_plan_complete(db: Session, session: ChatSession) -> None:
    with agent_scope("memory"):
        persist_working(db, session)
        write_episode_from_plan(db, session)
