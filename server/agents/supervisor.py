## Đây là trung tâm điều phối các agent khác nhau


from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from conversation import (
    ChatSession,
    chat_llm,
    run_conversation_turn,
    should_run_planner,
)
from lookup import apply_lookup
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

## Trích xuất semantic câu nói của user vừa rồi trong phiên chat 
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
"""
run_supervised_turn là một vòng hội thoại đầy đủ trước khi quyết định có chạy planner hay không.
Nó không tự tạo itinerary;
nó đọc memory → chat/slot-fill → gate địa điểm/lookup → ghi memory → trả kết quả cho main.py.

tin nhắn user
  → retrieve_memory          (đọc profile + facts + episodes)
  → đưa vào prompt chat
  → LLM slot-fill / trả lời
  → extract semantic         (LLM → MemoryExtraction)
  → persist_working          (lưu session)
  → write_semantic_from_turn (cập nhật profile + facts)
  → (khi plan xong) write_episode_from_plan
"""

def run_supervised_turn(
    db: Session,
    session: ChatSession, # session hiện tại của phiên hội thoại
    user_message: str, #tin nhắn người dùng vừa gửi 
) -> SupervisorResult:
## Lấy ra memory từ database
    with agent_scope("memory"):
        bundle = retrieve_memory(db, session.user_id, user_message)
    turn, previous_slots = run_conversation_turn(
        session,
        user_message,
        memory_block=bundle.as_prompt(),
    )
    turn = apply_place_or_quality_gate(session, turn, user_message)
    turn = apply_lookup(session, turn, user_message)
    route = turn.intent if turn.intent in ("chat", "plan", "refine", "recall", "place", "lookup") else "chat"
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
