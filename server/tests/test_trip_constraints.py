from app.domain.conversation import (
    merge_slots,
    slots_snapshot,
    synthesize_user_request,
    trip_request_from_slots,
)
from app.graph.nodes.common import _trip_payload
from app.schemas import ConversationTurn, PartialTripRequest
from packages.agent_runtime.contract import TripPayload
from packages.agent_runtime.runner import _trip_lines


BASE_SLOTS = {
    "origin": "Ho Chi Minh City",
    "destination": "Da Nang",
    "start_date": "2026-10-10",
    "end_date": "2026-10-13",
    "person": 2,
}


def test_conversation_turn_extracts_structured_constraints():
    turn = ConversationTurn(
        reply="Đã hiểu.",
        detected_language="vi",
        intent="plan",
        hard_constraints=["direct flights only"],
        soft_preferences=["hotel near the beach"],
        priorities=["price", "flight duration", "hotel rating"],
    )

    extracted = turn.to_extracted()

    assert extracted.hard_constraints == ["direct flights only"]
    assert extracted.soft_preferences == ["hotel near the beach"]
    assert extracted.priorities == ["price", "flight duration", "hotel rating"]


def test_constraints_accumulate_without_losing_previous_turns():
    first = merge_slots(
        BASE_SLOTS,
        PartialTripRequest(
            hard_constraints=["direct flights only"],
            soft_preferences=["hotel near the beach"],
        ),
    )
    second = merge_slots(
        first,
        PartialTripRequest(
            hard_constraints=["no overnight flights"],
            priorities=["price", "flight duration"],
        ),
    )

    assert second["hard_constraints"] == [
        "direct flights only",
        "no overnight flights",
    ]
    assert second["soft_preferences"] == ["hotel near the beach"]
    assert second["priorities"] == ["price", "flight duration"]


def test_constraints_reach_trip_state_and_agent_payload():
    slots = {
        **BASE_SLOTS,
        "hard_constraints": ["direct flights only"],
        "soft_preferences": ["hotel near the beach"],
        "priorities": ["price", "duration"],
    }

    snapshot = slots_snapshot(slots)
    plan = trip_request_from_slots(slots)
    payload = _trip_payload(plan)

    assert snapshot["hard_constraints"] == ["direct flights only"]
    assert plan.soft_preferences == ["hotel near the beach"]
    assert payload["priorities"] == ["price", "duration"]

    service_trip = TripPayload(**payload)
    prompt_lines = _trip_lines(service_trip)
    assert "hard_constraints: ['direct flights only']" in prompt_lines
    assert "soft_preferences: ['hotel near the beach']" in prompt_lines
    assert "priorities_highest_first: ['price', 'duration']" in prompt_lines

    request_text = synthesize_user_request(slots, "Lập kế hoạch")
    assert "Non-negotiable requirements: direct flights only" in request_text
    assert "Nice-to-have preferences: hotel near the beach" in request_text
    assert "Priority order (highest first): price > duration" in request_text
