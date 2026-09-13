"""Helper dung chung cho cac node: refresh, payload, goi /agent/run."""


import uuid
from app.core.telemetry import tracked_post
from app.graph.state import TripState


MAX_EXTRACTED_ACTIVITIES = 8

DEFAULT_REFRESH = ["flight", "hotel", "event", "activities"]

def _refresh_targets(state: TripState) -> list:
    refresh = state.get("refresh")
    if not refresh:
        return list(DEFAULT_REFRESH)
    return list(refresh)

def _should_skip_search(state: TripState, target: str, existing) -> bool:
    if target in _refresh_targets(state):
        return False
    return bool(existing)

def _trip_plan_is_complete(plan) -> bool:
    if not plan:
        return False
    return all([
        getattr(plan, "origin", None),
        getattr(plan, "destination", None),
        getattr(plan, "start_date", None),
        getattr(plan, "end_date", None),
        getattr(plan, "person", None),
    ])

def _agent_session_id(state: TripState) -> str:
    for key in ("session_id", "telemetry_run_id"):
        value = state.get(key)
        if value:
            return str(value)
    return str(uuid.uuid4())

def _agent_user_id(state: TripState) -> str:
    value = state.get("user_id")
    if value:
        return str(value)
    return str(uuid.uuid4())

def _dump_option(item):
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return item

def _feedback_text(state: TripState) -> str:
    parts = []
    if state.get("user_feedback"):
        parts.append(str(state["user_feedback"]))
    evaluation = state.get("evaluation_result")
    if evaluation is not None:
        feedback = getattr(evaluation, "feedback", None)
        if feedback:
            parts.append(str(feedback))
    return "\n".join(parts)

def _trip_payload(plan) -> dict:
    if not plan:
        return {}
    return {
        "origin": getattr(plan, "origin", None),
        "destination": getattr(plan, "destination", None),
        "start_date": getattr(plan, "start_date", None),
        "end_date": getattr(plan, "end_date", None),
        "person": getattr(plan, "person", None),
        "budget": getattr(plan, "budget", None),
        "interests": getattr(plan, "interests", None),
    }

def _call_agent_run(url: str, state: TripState, *, task: str, existing_options=None) -> dict:
    payload = {
        "user_id": _agent_user_id(state),
        "session_id": _agent_session_id(state),
        "task": task,
        "trip": _trip_payload(state.get("trip_plan")),
        "traveler_context": state.get("memory_context") or "",
        "feedback": _feedback_text(state),
        "existing_options": [_dump_option(item) for item in (existing_options or [])],
    }
    print(f"-> POST {url} task={task}")
    response = tracked_post(url, json=payload, timeout=120)
    response.raise_for_status()
    return response.json()

def _as_models(items, cls):
    result = []
    for item in items or []:
        if isinstance(item, cls):
            result.append(item)
            continue
        if isinstance(item, dict):
            try:
                result.append(cls(**item))
            except Exception as exc:
                print(f"-> skip invalid {cls.__name__}: {exc}")
    return result

def _parse_selected(data: dict, cls, options):
    raw = data.get("selected")
    if raw:
        parsed = _as_models([raw] if not isinstance(raw, list) else raw[:1], cls)
        if parsed:
            return parsed[0]
    return options[0] if options else None
