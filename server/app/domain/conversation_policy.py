"""Pure policy for turning LLM understanding into one conversation decision."""

from dataclasses import dataclass
from typing import List, Optional

from app.domain.lookup import infer_lookup_targets, normalize_lookup_targets
from app.schemas import ConversationTurn, REQUIRED_TRIP_FIELDS


@dataclass(frozen=True)
class ConversationDecision:
    """Validated action selected for the current conversational turn."""

    intent: str
    lookup_targets: List[str]
    ready_to_plan: bool
    missing_fields: List[str]
    clarification_fields: List[str]
    user_feedback: Optional[str]


def missing_required(slots: dict) -> List[str]:
    missing = []
    for key in REQUIRED_TRIP_FIELDS:
        value = (slots or {}).get(key)
        if value is None or value == "":
            missing.append(key)
        elif key == "person" and (not isinstance(value, int) or value <= 0):
            try:
                if int(value) <= 0:
                    missing.append(key)
            except (TypeError, ValueError):
                missing.append(key)
    return missing


def decide_conversation_turn(
    turn: ConversationTurn,
    *,
    slots: dict,
    has_plan: bool,
    user_message: str,
    messages: Optional[List[dict]] = None,
    llm_failed: bool = False,
) -> ConversationDecision:
    """Apply safety rules without re-interpreting natural language.

    The LLM owns intent recognition. Keyword inference is restricted to recovery:
    an explicit lookup with a missing target, or a failed LLM call.
    """

    intent = turn.intent
    targets = normalize_lookup_targets(turn.lookup_targets)
    missing = missing_required(slots)

    if intent in ("place", "recall"):
        targets = []
    elif intent == "lookup":
        if not targets:
            targets = infer_lookup_targets(user_message, messages, slots)
        if not targets:
            intent = "chat"
    elif llm_failed:
        targets = infer_lookup_targets(user_message, messages, slots)
        if targets:
            intent = "lookup"

    requested_plan = intent in ("plan", "refine")

    if intent == "refine" and not has_plan:
        intent = "plan" if not missing else "chat"
    elif intent in ("plan", "refine") and missing:
        intent = "chat"

    ready_to_plan = intent in ("plan", "refine") and not missing
    user_feedback = user_message if intent in ("plan", "refine") else None

    return ConversationDecision(
        intent=intent,
        lookup_targets=targets if intent == "lookup" else [],
        ready_to_plan=ready_to_plan,
        missing_fields=missing,
        clarification_fields=missing[:2] if requested_plan and missing else [],
        user_feedback=user_feedback,
    )
