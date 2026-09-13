"""Node xep hoat dong theo tung ngay va lap Itinerary."""


from app.core.llm import invoke_tool_schema, llm
from app.graph.nodes.common import MAX_EXTRACTED_ACTIVITIES, _refresh_targets
from app.graph.state import TripState
from app.schemas import Itinerary, ScheduledActivities


def activity_scheduling_agent(state: TripState) -> dict:
    """
    Schedules the activities day by day using LLM.
    Includes robust error handling for LLM tool call failures.
    And MOST IMPORTANTLY: Re-attaches coordinates to the scheduled activities.
    """
    print("--- Running Activity Scheduling Agent ---")
    
    extracted_activities = state.get("extracted_activities", [])
    events = state.get("events", [])
    trip_plan = state["trip_plan"]
    existing_itinerary = state.get("final_itinerary")
    refresh = _refresh_targets(state)

    if (
        "activities" not in refresh
        and "event" not in refresh
        and existing_itinerary
        and existing_itinerary.daily_plans
        and state.get("selected_flight")
        and state.get("selected_hotel")
    ):
        print("-> Reusing existing daily plans after flight/hotel-only refresh.")
        return {
            "final_itinerary": Itinerary(
                selected_flight=state["selected_flight"],
                selected_hotel=state["selected_hotel"],
                daily_plans=existing_itinerary.daily_plans,
            )
        }

    if not extracted_activities and not events:
        print("-> Missing data, cannot schedule.")
        return {"final_itinerary": None}

    print(f"-> Received {len(extracted_activities)} activities and {len(events)} events to schedule.")

    activities_to_schedule = extracted_activities[:MAX_EXTRACTED_ACTIVITIES]
    activity_lookup = {act.name: act for act in activities_to_schedule}

    activities_text = "\n".join([f"- {act.name}: {act.description} ({act.time_of_day})" for act in activities_to_schedule])
    events_text = "\n".join([f"- {evt.name} on {evt.date} at {evt.venue}" for evt in events[:5]])

    prompt = f"""
    You are an expert travel planner. Create a day-by-day itinerary for a {trip_plan.days}-day trip to {trip_plan.destination}.

    **Inputs:**
    - Trip Duration: {trip_plan.days} days
    - Activities to fit in:
    {activities_text}
    
    - Fixed Events (Must happen on their specific date):
    {events_text}

    **Instructions:**
    1. Distribute these activities logically across {trip_plan.days} days.
    2. Group nearby activities together to minimize travel time.
    3. Each day needs a mix of morning, afternoon, and evening. At most 4 activities per day.
    4. Call the `ScheduledActivities` tool with your final plan. Fully close the JSON.
    5. Use the EXACT activity names from the input list. No apostrophes or quotation marks in text fields.
    """

    try:
        scheduled_plan = invoke_tool_schema(llm, ScheduledActivities, prompt)
        for day_plan in scheduled_plan.daily_plans:
            for scheduled_act in day_plan.activities:
                original_act = activity_lookup.get(scheduled_act.name)
                
                if original_act and original_act.latitude and original_act.longitude:
                    scheduled_act.latitude = original_act.latitude
                    scheduled_act.longitude = original_act.longitude
                else:
                    for orig_name, orig_act in activity_lookup.items():
                        if scheduled_act.name in orig_name or orig_name in scheduled_act.name:
                            if orig_act.latitude and orig_act.longitude:
                                scheduled_act.latitude = orig_act.latitude
                                scheduled_act.longitude = orig_act.longitude
                                break

        if not state.get("selected_flight") or not state.get("selected_hotel"):
            print("-> Missing selected flight or hotel, cannot assemble itinerary.")
            return {"final_itinerary": None}

        final_itinerary = Itinerary(
            selected_flight=state['selected_flight'],
            selected_hotel=state['selected_hotel'],
            daily_plans=scheduled_plan.daily_plans
        )
        print("-> Final Itinerary Assembled Successfully (Coordinates Preserved).")
        return {"final_itinerary": final_itinerary}

    except Exception as e:
        print(f"-> FAILED: LLM could not generate a valid schedule: {e}")
        return {"final_itinerary": None}
