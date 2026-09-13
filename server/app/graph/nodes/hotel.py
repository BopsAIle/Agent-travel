"""Node hotel: goi hotel-service, fallback /search + LLM chon."""


from app.core.llm import llm, openai_model
from app.core.telemetry import tracked_invoke, tracked_post
from app.graph.nodes.common import (
    _as_models,
    _call_agent_run,
    _parse_selected,
    _should_skip_search,
)
from app.graph.state import TripState
from app.schemas import HotelInfo, HotelSelection


def _select_hotel_fallback(state: TripState, hotel_options: list) -> HotelInfo:
    trip_plan = state["trip_plan"]
    selection_llm = llm.bind_tools([HotelSelection])
    options_text = ""
    for i, opt in enumerate(hotel_options):
        options_text += f"Option {i}: Name: {opt.hotel_name}, Rating: {opt.rating}/10, Total Price: €{opt.total_price:.2f}\n"
    refinement_feedback = ""
    if state.get("refinement_count", 0) > 0 and state.get("evaluation_result"):
        refinement_feedback = (
            f"The previous attempt exceeded the budget. Feedback: "
            f"'{state['evaluation_result'].feedback}'."
        )
    traveler_feedback = state.get("user_feedback") or ""
    if traveler_feedback:
        refinement_feedback += f" The traveler asked: '{traveler_feedback}'."
    prompt = f"""
    You are an expert travel advisor. Select the best hotel.
    {refinement_feedback}
    USER PREFERENCES:
    - Budget: €{trip_plan.budget}
    HOTEL OPTIONS:
    {options_text}
    """
    ai_message = tracked_invoke(selection_llm, prompt, model=openai_model, provider="openai")
    if ai_message.tool_calls:
        selection = HotelSelection(**ai_message.tool_calls[0]["args"])
        if selection.best_option_index < len(hotel_options):
            return hotel_options[selection.best_option_index]
    return hotel_options[0]

def hotel_agent(state: TripState) -> dict:
    """POST /agent/run on hotel-service; fallback /search + LLM if the agent path fails."""
    print("--- Running Hotel Agent ---")
    trip_plan = state["trip_plan"]
    if not trip_plan:
        return {}

    if _should_skip_search(state, "hotel", state.get("selected_hotel")):
        print("-> Skipping hotel search (not in refresh).")
        return {}

    existing = list(state.get("hotel_options") or [])
    task = "refine" if existing else "search"
    try:
        data = _call_agent_run(
            "http://hotel-service:8001/agent/run",
            state,
            task=task,
            existing_options=existing,
        )
        hotel_options = _as_models(data.get("options"), HotelInfo)
        selected_hotel = _parse_selected(data, HotelInfo, hotel_options)
        print(f"-> Hotel reasoning: {data.get('reasoning')}")
        print(f"-> Hotel memory_hits: {data.get('memory_hits')}")
        return {"hotel_options": hotel_options, "selected_hotel": selected_hotel}
    except Exception as exc:
        print(f"-> Hotel /agent/run failed, fallback /search: {exc}")

    payload = {
        "destination": trip_plan.destination,
        "start_date": trip_plan.start_date,
        "end_date": trip_plan.end_date,
        "person": trip_plan.person,
    }
    try:
        response = tracked_post("http://hotel-service:8001/search", json=payload, timeout=60)
        response.raise_for_status()
        hotel_options = [HotelInfo(**item) for item in response.json()]
    except Exception as exc:
        print(f"-> ERROR calling Hotel /search: {exc}")
        return {"hotel_options": [], "selected_hotel": None}

    if not hotel_options:
        return {"hotel_options": [], "selected_hotel": None}
    selected_hotel = _select_hotel_fallback(state, hotel_options)
    return {"hotel_options": hotel_options, "selected_hotel": selected_hotel}
