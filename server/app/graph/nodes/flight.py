"""Node flight: goi flight-service, fallback /search + LLM chon."""


from app.core.llm import llm, openai_model
from app.core.telemetry import tracked_invoke, tracked_post
from app.graph.nodes.common import (
    _as_models,
    _call_agent_run,
    _parse_selected,
    _should_skip_search,
)
from app.core.config import FLIGHT_SERVICE_URL
from app.domain.planning_issues import classify_provider_error
from app.graph.state import TripState
from app.schemas import FlightInfo, FlightSelection


def _select_flight_fallback(state: TripState, flight_options: list) -> FlightInfo:
    selection_llm = llm.bind_tools([FlightSelection])
    options_text = ""
    for i, opt in enumerate(flight_options):
        options_text += f"Option {i}: Airline: {opt.departure_leg.airline}, Price: €{opt.price:.2f}, Duration: {opt.total_duration_minutes}m\n"
    traveler_feedback = state.get("user_feedback") or ""
    feedback_block = f"\nTraveler request: {traveler_feedback}\n" if traveler_feedback else ""
    prompt = f"""
    You are an expert flight travel agent. Select the BEST flight option.
    CRITERIA:
    1. Budget: {state['trip_plan'].budget} EUR (already converted from the traveler's currency).
    2. Convenience: Short duration is better.
    3. Non-negotiable requirements: {state['trip_plan'].hard_constraints or 'None'}.
    4. Nice-to-have preferences: {state['trip_plan'].soft_preferences or 'None'}.
    5. User priority order (highest first): {state['trip_plan'].priorities or 'Not specified'}.
    {feedback_block}
    Options:
    {options_text}
    """
    ai_message = tracked_invoke(selection_llm, prompt, model=openai_model, provider="openai")
    if ai_message.tool_calls:
        selection = FlightSelection(**ai_message.tool_calls[0]["args"])
        if selection.best_option_index < len(flight_options):
            return flight_options[selection.best_option_index]
    return flight_options[0]

def flight_agent(state: TripState) -> dict:
    """POST /agent/run on flight-service; fallback /search + LLM if the agent path fails."""
    print("--- Running Flight Agent ---")
    trip_plan = state["trip_plan"]
    if not trip_plan:
        return {}

    if _should_skip_search(state, "flight", state.get("selected_flight")):
        print("-> Skipping flight search (not in refresh).")
        return {}

    existing = list(state.get("flight_options") or [])
    task = "refine" if existing else "search"
    try:
        data = _call_agent_run(
            f"{FLIGHT_SERVICE_URL}/agent/run",
            state,
            task=task,
            existing_options=existing,
        )
        flight_options = _as_models(data.get("options"), FlightInfo)
        selected_flight = _parse_selected(data, FlightInfo, flight_options)
        print(f"-> Flight reasoning: {data.get('reasoning')}")
        print(f"-> Flight memory_hits: {data.get('memory_hits')}")
        errors = [str(item) for item in (data.get("errors") or []) if item]
        if errors and not flight_options:
            return {
                "flight_options": [],
                "selected_flight": None,
                "flight_failure_reason": classify_provider_error(errors[0]),
            }
        return {
            "flight_options": flight_options,
            "selected_flight": selected_flight,
            "flight_failure_reason": None if selected_flight else "no_results",
        }
    except Exception as exc:
        print(f"-> Flight /agent/run failed, fallback /search: {exc}")

    payload = {
        "origin": trip_plan.origin,
        "destination": trip_plan.destination,
        "start_date": trip_plan.start_date,
        "end_date": trip_plan.end_date,
        "person": trip_plan.person,
    }
    try:
        response = tracked_post(f"{FLIGHT_SERVICE_URL}/search", json=payload, timeout=60)
        response.raise_for_status()
        flight_options = [FlightInfo(**item) for item in response.json()]
    except Exception as exc:
        print(f"-> ERROR calling Flight /search: {exc}")
        return {
            "flight_options": [],
            "selected_flight": None,
            "flight_failure_reason": classify_provider_error(str(exc)),
        }

    if not flight_options:
        return {
            "flight_options": [],
            "selected_flight": None,
            "flight_failure_reason": "no_results",
        }
    selected_flight = _select_flight_fallback(state, flight_options)
    return {
        "flight_options": flight_options,
        "selected_flight": selected_flight,
        "flight_failure_reason": None,
    }
