"""Node event: goi event-service, fallback /search_events + LLM loc."""


import json
from app.core.llm import llm, openai_model
from app.core.telemetry import tracked_invoke, tracked_post
from app.graph.nodes.common import _as_models, _call_agent_run, _should_skip_search
from app.core.config import EVENT_SERVICE_URL
from app.graph.state import TripState
from app.schemas import EventInfo, SelectedEvents


def event_agent(state: TripState) -> dict:
    """POST /agent/run on event-service; fallback /search_events + LLM if needed."""
    print("--- Running Event Agent ---")
    trip_plan = state["trip_plan"]
    if not trip_plan or not trip_plan.interests:
        return {"events": []}

    if _should_skip_search(state, "event", state.get("events") is not None):
        print("-> Skipping event search (not in refresh).")
        return {}

    existing = list(state.get("events") or [])
    task = "refine" if existing else "search"
    try:
        data = _call_agent_run(
            f"{EVENT_SERVICE_URL}/agent/run",
            state,
            task=task,
            existing_options=existing,
        )
        events = _as_models(data.get("options"), EventInfo)
        if not events and data.get("selected"):
            events = _as_models(
                [data["selected"]] if not isinstance(data["selected"], list) else data["selected"],
                EventInfo,
            )
        print(f"-> Event reasoning: {data.get('reasoning')}")
        print(f"-> Event memory_hits: {data.get('memory_hits')}")
        return {"events": events}
    except Exception as exc:
        print(f"-> Event /agent/run failed, fallback /search_events: {exc}")

    payload = {
        "city": trip_plan.destination,
        "start_date": trip_plan.start_date,
        "end_date": trip_plan.end_date,
    }
    try:
        response = tracked_post(f"{EVENT_SERVICE_URL}/search_events", json=payload, timeout=30)
        response.raise_for_status()
        all_events = [EventInfo(**item) for item in response.json()]
    except Exception as exc:
        print(f"-> ERROR calling Event /search_events: {exc}")
        return {"events": []}

    if not all_events:
        return {"events": []}

    selected_llm = llm.bind_tools([SelectedEvents])
    events_json = json.dumps([event.model_dump() for event in all_events])
    prompt = f"""
    You are an expert event curator. Based on a user's interests, select the most relevant events.

    User's Interests: {', '.join(trip_plan.interests)}

    LIST OF AVAILABLE EVENTS:
    {events_json}

    Remove duplicates and select the top 3-4 most relevant events. Call `SelectedEvents`.
    """
    ai_message = tracked_invoke(selected_llm, prompt, model=openai_model, provider="openai")
    if not ai_message.tool_calls:
        return {"events": all_events[:5]}
    selected_list = SelectedEvents(**ai_message.tool_calls[0]["args"])
    return {"events": selected_list.events}
