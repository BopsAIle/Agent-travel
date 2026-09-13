"""Node trich xuat hoat dong tu ket qua tim kiem web."""


from app.core.llm import invoke_tool_schema, llm
from app.core.telemetry import tracked_post
from app.graph.nodes.common import (
    MAX_EXTRACTED_ACTIVITIES,
    _as_models,
    _call_agent_run,
    _should_skip_search,
)
from app.core.config import ACTIVITY_SERVICE_URL
from app.graph.state import TripState
from app.schemas import Activity, ExtractedActivities


def activity_extraction_agent(state: TripState) -> dict:
    """POST /agent/run on activity-service; fallback /search_activities + LLM extract."""
    print("--- Running Activity Extraction Agent ---")
    trip_plan = state["trip_plan"]
    if not trip_plan:
        return {}

    if _should_skip_search(state, "activities", state.get("extracted_activities")):
        print("-> Skipping activity extraction (not in refresh).")
        return {}

    existing = list(state.get("extracted_activities") or [])
    task = "refine" if existing else "search"
    try:
        data = _call_agent_run(
            f"{ACTIVITY_SERVICE_URL}/agent/run",
            state,
            task=task,
            existing_options=existing,
        )
        activities = _as_models(data.get("options"), Activity)[:MAX_EXTRACTED_ACTIVITIES]
        print(f"-> Activity reasoning: {data.get('reasoning')}")
        print(f"-> Activity memory_hits: {data.get('memory_hits')}")
        return {"extracted_activities": activities}
    except Exception as exc:
        print(f"-> Activity /agent/run failed, fallback /search_activities: {exc}")

    payload = {
        "destination": trip_plan.destination,
        "interests": trip_plan.interests,
    }
    try:
        response = tracked_post(
            f"{ACTIVITY_SERVICE_URL}/search_activities", json=payload, timeout=60
        )
        response.raise_for_status()
        raw_activity_data = response.json()
    except Exception as exc:
        print(f"-> ERROR calling Activity /search_activities: {exc}")
        return {"extracted_activities": []}

    if not raw_activity_data or "No relevant activities found" in str(raw_activity_data):
        return {"extracted_activities": []}

    prompt = f"""
    You are a data extraction expert. Analyze the web search text and extract physical, geocodable places.

    **CRITICAL INSTRUCTIONS:**
    - Extract **at most {MAX_EXTRACTED_ACTIVITIES}** of the most iconic physical places. Do not exceed that number.
    - Only real physical locations: museums, monuments, parks, squares, famous buildings, neighborhoods.
    - Avoid events, exhibitions, festivals, awards, or abstract concepts.
    - Keep each description under 15 words.
    - Do not use apostrophes or quotation marks in any field. Write Sant Angelo not Sant'Angelo.
    - Use ASCII hyphens only. Fully close the tool JSON.

    **RAW SEARCH RESULTS:**
    ---
    {raw_activity_data}
    ---

    Call `ExtractedActivities` with at most {MAX_EXTRACTED_ACTIVITIES} physical places.
    """
    try:
        extracted = invoke_tool_schema(llm, ExtractedActivities, prompt)
        activities = extracted.activities[:MAX_EXTRACTED_ACTIVITIES]
        return {"extracted_activities": activities}
    except Exception as exc:
        print(f"-> LLM failed to extract any activities: {exc}")
        return {"extracted_activities": []}
