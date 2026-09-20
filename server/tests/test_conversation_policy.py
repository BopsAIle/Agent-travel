from types import SimpleNamespace

from app.domain.conversation_policy import decide_conversation_turn, missing_required
from app.domain.lookup import apply_lookup
from app.schemas import ConversationTurn


COMPLETE_SLOTS = {
    "origin": "Ho Chi Minh City",
    "destination": "Da Nang",
    "start_date": "2026-10-10",
    "end_date": "2026-10-13",
    "person": 2,
}


def _turn(intent="chat", **updates):
    payload = {
        "reply": "LLM reply",
        "detected_language": "vi",
        "intent": intent,
        "ready_to_plan": False,
    }
    payload.update(updates)
    return ConversationTurn(**payload)


def test_chat_intent_is_not_overridden_by_lookup_keywords():
    decision = decide_conversation_turn(
        _turn("chat"),
        slots=COMPLETE_SLOTS,
        has_plan=False,
        user_message="Giải thích giúp tôi vì sao giá vé máy bay thay đổi",
    )

    assert decision.intent == "chat"
    assert decision.lookup_targets == []
    assert decision.ready_to_plan is False


def test_explicit_lookup_can_recover_a_missing_target():
    decision = decide_conversation_turn(
        _turn("lookup"),
        slots=COMPLETE_SLOTS,
        has_plan=False,
        user_message="Cho tôi xem các chuyến bay",
    )

    assert decision.intent == "lookup"
    assert decision.lookup_targets == ["flight"]
    assert decision.ready_to_plan is False


def test_plan_with_missing_fields_waits_without_losing_missing_state():
    decision = decide_conversation_turn(
        _turn("plan", ready_to_plan=True),
        slots={"destination": "Da Nang"},
        has_plan=False,
        user_message="Lập lịch trình đi Đà Nẵng",
    )

    assert decision.intent == "chat"
    assert decision.ready_to_plan is False
    assert decision.missing_fields == ["origin", "start_date", "end_date", "person"]
    assert decision.clarification_fields == ["origin", "start_date"]


def test_complete_chat_does_not_start_planner_just_from_ready_flag():
    decision = decide_conversation_turn(
        _turn("chat", ready_to_plan=True),
        slots=COMPLETE_SLOTS,
        has_plan=False,
        user_message="Tôi nên mang theo gì?",
    )

    assert decision.intent == "chat"
    assert decision.ready_to_plan is False


def test_complete_plan_is_ready_and_keeps_feedback():
    message = "Hãy lập lịch trình đầy đủ"
    decision = decide_conversation_turn(
        _turn("plan"),
        slots=COMPLETE_SLOTS,
        has_plan=False,
        user_message=message,
    )

    assert decision.intent == "plan"
    assert decision.ready_to_plan is True
    assert decision.user_feedback == message


def test_invalid_party_size_is_missing():
    assert missing_required({**COMPLETE_SLOTS, "person": 0}) == ["person"]


def test_lookup_executor_does_not_reroute_chat_from_keywords():
    session = SimpleNamespace(messages=[], slots=COMPLETE_SLOTS, language="vi")
    turn = _turn("chat")

    result = apply_lookup(session, turn, "Giải thích vì sao giá vé máy bay thay đổi")

    assert result is turn
    assert result.intent == "chat"
