
import os
import json
import uuid
import markdown2
import folium
from folium import plugins
from typing import Optional, Type, TypeVar
from pydantic import BaseModel
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from state import TripState
from dotenv import load_dotenv
from datetime import datetime, timedelta 
from schemas import *
from telemetry import tracked_invoke, tracked_post
from quality import sanitize_and_flag
from reply_format import (
    format_event_options_markdown,
    format_flight_options_markdown,
    format_hotel_options_markdown,
) 

load_dotenv()

openai_api_key = os.getenv("OPENAI_API_KEY")
openai_model = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
openai_reasoning_effort = os.getenv("OPENAI_REASONING_EFFORT", "low")
gemini_api_key = os.getenv("GEMINI_API_KEY")

if not all([openai_api_key, gemini_api_key]):
    raise ValueError("OPENAI_API_KEY or GEMINI_API_KEY is missing from .env file!")


def _is_gpt5_family(model: str) -> bool:
    return (model or "").lower().startswith("gpt-5")


def make_chat_openai(*, max_tokens: int, temperature: float = 0) -> ChatOpenAI:
    """Build a ChatOpenAI client compatible with GPT-5.6 tool calling."""
    kwargs = {
        "model": openai_model,
        "api_key": openai_api_key,
        "max_retries": 2,
        "max_tokens": max_tokens,
    }
    if _is_gpt5_family(openai_model):
        # Chat Completions rejects GPT-5.6 function tools unless reasoning_effort is none.
        kwargs["temperature"] = None
        kwargs["use_responses_api"] = True
        kwargs["reasoning_effort"] = openai_reasoning_effort
    else:
        kwargs["temperature"] = temperature
    return ChatOpenAI(**kwargs)


llm = make_chat_openai(max_tokens=4096, temperature=0)

llm_gemini = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash", 
    temperature=0.1,
    google_api_key=gemini_api_key
)

SchemaT = TypeVar("SchemaT", bound=BaseModel)
MAX_EXTRACTED_ACTIVITIES = 8


def _failed_generation_from_exception(exc: Exception) -> Optional[str]:
    """Pull a truncated tool-call payload out of a 400 tool_use_failed error."""
    current: Optional[BaseException] = exc
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        body = getattr(current, "body", None)
        if isinstance(body, dict):
            gen = (body.get("error") or {}).get("failed_generation")
            if isinstance(gen, str) and gen.strip():
                return gen
        response = getattr(current, "response", None)
        if response is not None:
            try:
                data = response.json()
                gen = (data.get("error") or {}).get("failed_generation")
                if isinstance(gen, str) and gen.strip():
                    return gen
            except Exception:
                pass
        current = getattr(current, "__cause__", None) or getattr(current, "__context__", None)

    text = str(exc)
    marker = "failed_generation"
    idx = text.find(marker)
    if idx == -1:
        return None
    rest = text[idx + len(marker):]
    brace = rest.find("{")
    if brace == -1:
        return None
    return rest[brace:]


def _close_truncated_json(text: str) -> Optional[dict]:
    """Best-effort parse of truncated / lightly invalid tool JSON."""
    start = text.find("{")
    if start == -1:
        return None
    chunk = text[start:].replace("\\'", "'")

    def try_load(candidate: str) -> Optional[dict]:
        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None

    parsed = try_load(chunk)
    if parsed:
        return parsed

    last = len(chunk)
    while last > 0:
        last = chunk.rfind("}", 0, last)
        if last == -1:
            break
        prefix = chunk[: last + 1].rstrip().rstrip(",")
        missing_square = prefix.count("[") - prefix.count("]")
        missing_curly = prefix.count("{") - prefix.count("}")
        if missing_square < 0 or missing_curly < 0:
            continue
        repaired = prefix + ("]" * missing_square) + ("}" * missing_curly)
        parsed = try_load(repaired)
        if parsed:
            return parsed
    return None


def _schema_from_parsed(schema: Type[SchemaT], parsed: dict) -> SchemaT:
    args = parsed.get("arguments", parsed)
    if isinstance(args, str):
        args = _close_truncated_json(args) or {}
    if not isinstance(args, dict):
        raise ValueError("Tool arguments were not an object")
    fields = set(schema.model_fields)
    return schema(**{k: v for k, v in args.items() if k in fields})


def _scrub_schema_result(result: SchemaT) -> SchemaT:
    """Drop looping prose sometimes salvaged from a failed tool call."""
    reply = getattr(result, "reply", None)
    if not isinstance(reply, str):
        return result
    cleaned, bad = sanitize_and_flag(reply)
    if not bad and cleaned == reply:
        return result
    try:
        result.reply = "" if bad else cleaned
    except Exception:
        return result
    if bad:
        print("-> Dropped degenerate reply from tool payload.")
    return result


def invoke_tool_schema(model, schema: Type[SchemaT], prompt: str, retries: int = 3) -> SchemaT:
    """Call LLM tools, and salvage JSON when a truncated tool call is rejected."""
    bound = model.bind_tools([schema], tool_choice=schema.__name__)
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        try:
            message = tracked_invoke(bound, prompt)
            if message.tool_calls:
                return _scrub_schema_result(schema(**message.tool_calls[0]["args"]))
            print(f"-> Attempt {attempt + 1}: LLM did not call {schema.__name__}. Retrying...")
        except Exception as e:
            last_error = e
            print(f"-> Attempt {attempt + 1} Error: {e}")
            gen = _failed_generation_from_exception(e)
            if gen:
                parsed = _close_truncated_json(gen)
                if parsed:
                    try:
                        result = _scrub_schema_result(_schema_from_parsed(schema, parsed))
                        print(f"-> Recovered truncated {schema.__name__} JSON from LLM error.")
                        return result
                    except Exception as parse_error:
                        print(f"-> Recovered JSON failed schema validation: {parse_error}")
    if last_error:
        raise last_error
    raise ValueError(f"LLM did not return a valid {schema.__name__}")

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

llm_gemini = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash", 
    temperature=0.1,
    google_api_key=gemini_api_key
)

#Node planner dùng trích xuất thông tin đầu vào của user sau đó 
#Lớp này chỉ trích xuất các field nếu đã đủ các fields còn conversation thì sẽ yêu cầu user nhập lại nếu còn thiếu field
def planner_agent(state: TripState) -> dict:
    """
    Takes the user request and converts it into a structured TripRequest object
    using the robust .bind_tools() method.
    """
    print("--- Running Planner Agent ---")

    existing = state.get("trip_plan")
    if _trip_plan_is_complete(existing):
        print("-> Using pre-extracted trip plan; skipping LLM parse.")
        return {"trip_plan": existing, "refinement_count": state.get("refinement_count") or 0}
    ## llm đại diện cho 1 client gửi API request
    planner_llm = llm.bind_tools([TripRequest])
    
    prompt = f"""
    You are an expert at parsing user travel requests.
    Parse the following user request into a structured TripRequest object.
    Extract the origin, destination, start date, end date, number of people, budget, and key interests.
    Today's date is {datetime.now().strftime('%Y-%m-%d')}. Dates must be in YYYY-MM-DD format.
    If the request omits a preference that appears in traveler memory, you may use it.

    Traveler memory/preferences: {state.get("memory_context") or "None"}
    User Request: "{state['user_request']}"
    """
    
    ai_message = tracked_invoke(planner_llm, prompt, model=openai_model, provider="openai")
    
    if not ai_message.tool_calls:
        raise ValueError("Planner agent failed to parse the user request into a structured plan.")
        
    tool_call = ai_message.tool_calls[0]
    plan = TripRequest(**tool_call['args'])
    
    print(f"-> Structured Plan: {plan.model_dump_json(indent=2)}")
    
    return {"trip_plan": plan, "refinement_count": 0}


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
    1. Budget: {state['trip_plan'].budget}.
    2. Convenience: Short duration is better.
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
            "http://flight-service:8000/agent/run",
            state,
            task=task,
            existing_options=existing,
        )
        flight_options = _as_models(data.get("options"), FlightInfo)
        selected_flight = _parse_selected(data, FlightInfo, flight_options)
        print(f"-> Flight reasoning: {data.get('reasoning')}")
        print(f"-> Flight memory_hits: {data.get('memory_hits')}")
        return {"flight_options": flight_options, "selected_flight": selected_flight}
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
        response = tracked_post("http://flight-service:8000/search", json=payload, timeout=60)
        response.raise_for_status()
        flight_options = [FlightInfo(**item) for item in response.json()]
    except Exception as exc:
        print(f"-> ERROR calling Flight /search: {exc}")
        return {"flight_options": [], "selected_flight": None}

    if not flight_options:
        return {"flight_options": [], "selected_flight": None}
    selected_flight = _select_flight_fallback(state, flight_options)
    return {"flight_options": flight_options, "selected_flight": selected_flight}


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
            "http://event-service:8004/agent/run",
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
        response = tracked_post("http://event-service:8004/search_events", json=payload, timeout=30)
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



def data_aggregator_agent(state: TripState) -> dict:
    """A simple node to act as a synchronization point for parallel branches."""
    print("--- Aggregating Flight, Hotel, and Event data ---")
   
    return {}



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
            "http://activity-service:8002/agent/run",
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
            "http://activity-service:8002/search_activities", json=payload, timeout=60
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


def geocoding_agent(state: TripState) -> dict:
    """POST /agent/run on geocoding-service; fallback /geocode per activity."""
    print("--- Running Geocoding Agent ---")
    activities = state.get("extracted_activities")
    if not activities:
        return {}

    if "activities" not in _refresh_targets(state) and all(
        getattr(activity, "latitude", None) and getattr(activity, "longitude", None)
        for activity in activities
    ):
        print("-> Skipping geocoding (activities not in refresh).")
        return {}

    dest = state["trip_plan"].destination if state.get("trip_plan") else ""
    existing = []
    for activity in activities:
        name = getattr(activity, "name", None) or (activity.get("name") if isinstance(activity, dict) else "")
        existing.append({"name": name, "query": f"{name}, {dest}", "destination": dest})

    try:
        data = _call_agent_run(
            "http://geocoding-service:8003/agent/run",
            state,
            task="search",
            existing_options=existing,
        )
        coords_by_query = {}
        coords_by_name = {}
        for item in data.get("options") or []:
            if not isinstance(item, dict):
                continue
            if item.get("query"):
                coords_by_query[str(item["query"]).lower()] = item
            if item.get("name"):
                coords_by_name[str(item["name"]).lower()] = item
        updated = []
        for activity in activities:
            name = getattr(activity, "name", "")
            query = f"{name}, {dest}"
            hit = coords_by_query.get(query.lower()) or coords_by_name.get(name.lower())
            if hit and hit.get("latitude") and hit.get("longitude"):
                activity.latitude = hit["latitude"]
                activity.longitude = hit["longitude"]
                print(f"-> Geocoded: {name}")
            updated.append(activity)
        print(f"-> Geocoding reasoning: {data.get('reasoning')}")
        print(f"-> Geocoding memory_hits: {data.get('memory_hits')}")
        return {"extracted_activities": updated}
    except Exception as exc:
        print(f"-> Geocoding /agent/run failed, fallback /geocode: {exc}")

    updated_activities = []
    for activity in activities:
        search_query = f"{activity.name}, {dest}"
        try:
            response = tracked_post(
                "http://geocoding-service:8003/geocode",
                json={"query": search_query},
                timeout=30,
            )
            if response.status_code == 200:
                payload = response.json()
                if payload.get("latitude") and payload.get("longitude"):
                    activity.latitude = payload["latitude"]
                    activity.longitude = payload["longitude"]
                    print(f"-> Geocoded: {activity.name}")
        except Exception as inner:
            print(f"-> Error geocoding {activity.name}: {inner}")
        updated_activities.append(activity)
    return {"extracted_activities": updated_activities}



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
    


def evaluator_agent(state: TripState) -> dict:
    print("--- Running Smart Evaluator Agent (High IQ Mode) ---")
    trip_plan = state['trip_plan']
    selected_flight = state['selected_flight']
    selected_hotel = state['selected_hotel']
    flight_options = state['flight_options']
    hotel_options = state['hotel_options']
    refinement_count = state.get('refinement_count', 0)
    
    if not selected_flight or not selected_hotel:
        return {
            "evaluation_result": EvaluationResult(
                action="APPROVE",
                feedback="Skipped budget evaluation because flight or hotel data is missing.",
                total_cost=0,
            ),
            "refinement_count": refinement_count + 1,
        }

    flight_and_hotel_cost = selected_flight.price + selected_hotel.total_price 
    daily_spending = trip_plan.daily_spending_budget if trip_plan.daily_spending_budget else 0
    total_daily_spending = daily_spending * trip_plan.person * trip_plan.days
    total_cost = flight_and_hotel_cost + total_daily_spending
    budget = trip_plan.budget

    if budget is None:
        return {
            "evaluation_result": EvaluationResult(
                action="APPROVE",
                feedback="Approved because no total budget was provided.",
                total_cost=total_cost,
            ),
            "refinement_count": refinement_count + 1,
        }


    next_hotel_info = "None"
    if len(hotel_options) > refinement_count + 1:
        h = hotel_options[refinement_count + 1]
        diff = selected_hotel.total_price - h.total_price
        next_hotel_info = f"""
        Name: {h.hotel_name}
        Price: €{h.total_price} (Saves €{diff:.2f})
        Rating: {h.rating} (Current is {selected_hotel.rating})
        """

    next_flight_info = "None"
    if len(flight_options) > refinement_count + 1:
        f = flight_options[refinement_count + 1]
        diff = selected_flight.price - f.price
        duration_diff = f.departure_leg.duration_minutes - selected_flight.departure_leg.duration_minutes
        duration_msg = f"{duration_diff} mins longer" if duration_diff > 0 else f"{abs(duration_diff)} mins shorter"
        
        next_flight_info = f"""
        Airline: {f.departure_leg.airline}
        Price: €{f.price} (Saves €{diff:.2f})
        Duration Change: {duration_msg}
        Stops: {'Direct' if not f.departure_leg.is_layover else 'Has Layover'}
        """

    evaluator_llm = llm_gemini.bind_tools([EvaluationResult])

    prompt = f"""
    You are an expert Travel Consultant. Your goal is to maximize the user's experience while trying to respect the budget.
    
    **Current Status:**
    - Budget: €{budget}
    - Total Cost: €{total_cost:.2f}
    - Status: {'Over Budget' if total_cost > budget else 'Within Budget'}

    **Current Selection Quality:**
    - Flight: {selected_flight.departure_leg.airline}, Duration: {selected_flight.departure_leg.duration_minutes} mins, Price: €{selected_flight.price}
    - Hotel: {selected_hotel.hotel_name}, Rating: {selected_hotel.rating}/10, Price: €{selected_hotel.total_price}

    **Alternative Options for Refinement:**
    - Option A (Cheaper Hotel): {next_hotel_info}
    - Option B (Cheaper Flight): {next_flight_info}

    **Strategic Rules (Think carefully):**
    1. If **Within Budget**: APPROVE immediately.
    2. If **Over Budget**: You must refine, BUT choose the "Lesser of Two Evils":
       - **Don't just pick the biggest saving.** Look at the Quality Trade-off.
       - If the Cheaper Flight adds 5+ hours of travel time for only €10 saving, REJECT IT.
       - If the Cheaper Hotel drops the rating from 9.0 to 6.0, try to avoid it unless necessary.
       - If both options are terrible (huge quality drop), pick the one that saves the most money to fix the budget.
       - If one option saves a lot of money with minimal quality loss (e.g., same flight duration, similar hotel rating), PICK THAT ONE.

    3. **Edge Case:** If the plan is slightly over budget (e.g., <5%) but the cheaper alternatives are terrible (bad ratings, long flights), you can APPROVE it. But explain why in the feedback (e.g., "Slightly over budget, but alternatives compromise quality too much").

    Make a decision: APPROVE, REFINE_FLIGHT, or REFINE_HOTEL.
    """

    try:
        ai_message = tracked_invoke(evaluator_llm, prompt, model="gemini-2.5-flash", provider="google")
        
        if not ai_message.tool_calls:
            print(f"Gemini Response (No Tool): {ai_message.content}")
            return {"evaluation_result": EvaluationResult(action="APPROVE", feedback="Auto-approved (Gemini didn't invoke tool)", total_cost=total_cost), "refinement_count": refinement_count + 1}
            
        tool_call = ai_message.tool_calls[0]
        result = EvaluationResult(**tool_call['args'])
        result.total_cost = total_cost
        
        print(f"-> Gemini Decision: {result.action}. Reason: {result.feedback}")
        return {"evaluation_result": result, "refinement_count": refinement_count + 1}

    except Exception as e:
        print(f"Gemini Error: {e}")
        return {"evaluation_result": EvaluationResult(action="APPROVE", feedback="Approved due to evaluator error.", total_cost=total_cost), "refinement_count": refinement_count + 1}



MAX_REFINEMENTS = 2

def should_refine_or_end(state: TripState):
    """
    Reads the action from the evaluation result to route the graph.
    """
    print("--- Routing based on Evaluation ---")
    action = state["evaluation_result"].action
    count = state.get('refinement_count', 0)

    if count >= MAX_REFINEMENTS:
        print(f"-> Maximum refinement count ({MAX_REFINEMENTS}) reached. Finishing.")
        return "end"
    
    if action == "APPROVE":
        print("-> Plan approved. Finishing.")
        return "end"
    
    if action == "REFINE_HOTEL":
        print(f"-> Plan hotel refinement required. Looping back to hotel_agent (Attempt {count}).")
        current_index = state['hotel_options'].index(state['selected_hotel'])

        if current_index + 1 < len(state['hotel_options']):
            state['selected_hotel'] = state['hotel_options'][current_index + 1]
        return "refine_hotel" 

    elif action == "REFINE_FLIGHT":
        print(f"-> Plan flight refinement required. Looping back to flight_agent (Attempt {count}).")
        current_index = state['flight_options'].index(state['selected_flight'])
        if current_index + 1 < len(state['flight_options']):
            state['selected_flight'] = state['flight_options'][current_index + 1]
        return "refine_flight"


def map_generator_node(state: TripState) -> dict:
    """Generates an interactive Folium map from the final itinerary and returns its HTML content."""
    print("--- Running Map Generator ---")
    final_itinerary = state.get("final_itinerary")

    if final_itinerary and final_itinerary.daily_plans:
        geocoded_count = sum(1 for day in final_itinerary.daily_plans for act in day.activities if act.latitude)
        print(f"-> Itinerary received. Found {geocoded_count} geocoded activities to plot on the map.")
    
    

    if not final_itinerary or not final_itinerary.daily_plans:
        return {"map_html": None} 

    first_coord = None
    all_coords = [] 
    for day in final_itinerary.daily_plans:
        for activity in day.activities:
            if activity.latitude and activity.longitude:
                coord = (activity.latitude, activity.longitude)
                all_coords.append(coord)
                if first_coord is None:
                    first_coord = coord
    
    if not first_coord:
        print("-> No coordinates found in the itinerary to create a map.")
        return {"map_html": None}

    m = folium.Map(location=first_coord, zoom_start=13)

    marker_cluster = folium.plugins.MarkerCluster().add_to(m)
    
    colors = ['blue', 'green', 'purple', 'orange', 'darkred', 'cadetblue', 'pink', 'lightgray']
    
    activity_counter = 1
    for i, day_plan in enumerate(final_itinerary.daily_plans):
        day_color = colors[i % len(colors)] 
        for activity in day_plan.activities:
            if activity.latitude and activity.longitude:
                popup_html = f"<b>Day {day_plan.day}: {activity.name}</b><br>{activity.description}"
                folium.Marker(
                    [activity.latitude, activity.longitude],
                    popup=popup_html,
                    tooltip=f"Day {day_plan.day} - {activity_counter}. {activity.name}",
                    icon=folium.Icon(color=day_color, icon='info-sign')
                ).add_to(marker_cluster) 
                activity_counter += 1

    if all_coords:
        m.fit_bounds(m.get_bounds())

    map_html_content = m._repr_html_()
    
    print(f"-> Interactive map HTML generated.")
    
    return {"map_html": map_html_content}



VI_MONTHS = [
    "", "tháng 1", "tháng 2", "tháng 3", "tháng 4", "tháng 5", "tháng 6",
    "tháng 7", "tháng 8", "tháng 9", "tháng 10", "tháng 11", "tháng 12",
]

REPORT_LABELS = {
    "en": {
        "failed_title": "Trip Plan Could Not Be Generated",
        "no_flights": "Sorry, no flights matching your criteria were found.",
        "no_hotels": "Sorry, no hotels matching your criteria were found.",
        "failed_generic": "A valid trip plan could not be generated with the available options. Please try modifying your request.",
        "title": "Your Trip to {destination} ({start} - {end})",
        "budget_summary": "Budget Summary",
        "flight_hotel_cost": "Flight + Hotel Cost",
        "daily_spending": "Estimated Daily Spending (for {days} days)",
        "total_cost": "Total Estimated Cost",
        "your_budget": "Your Total Budget",
        "under_budget": "Plan is **€{amount:,.2f} under budget**.",
        "over_budget": "Plan is **€{amount:,.2f} over budget**.",
        "status": "Status",
        "flight_info": "Flight Information",
        "airline": "Airline",
        "total_price_people": "Total Price (for {person} people)",
        "time": "Time",
        "details": "Details",
        "airport": "Airport",
        "depart": "Depart",
        "return": "Return",
        "total_journey": "Total Journey",
        "layover": "Layover",
        "at": "at",
        "arriving": "Arriving At",
        "other_flights": "Other Booking.com options",
        "other_hotels": "Other hotel options",
        "hotel_info": "Hotel Information",
        "rating": "Rating",
        "based_on": "based on {count} reviews",
        "taxes": "Taxes and Fees",
        "total_price_stay": "Total Price (for {nights} nights, {person} people)",
        "location": "Location",
        "on_maps": "on Google Maps",
        "events": "Events & Concerts During Your Stay",
        "date": "Date",
        "event": "Event",
        "venue": "Venue",
        "daily": "Daily Itinerary",
        "no_activities": "No specific activities planned for this trip.",
        "day": "Day {day}",
    },
    "vi": {
        "failed_title": "Không tạo được kế hoạch chuyến đi",
        "no_flights": "Không tìm thấy chuyến bay phù hợp.",
        "no_hotels": "Không tìm thấy khách sạn phù hợp.",
        "failed_generic": "Không tạo được kế hoạch hợp lệ với các lựa chọn hiện có. Bạn thử điều chỉnh yêu cầu nhé.",
        "title": "Chuyến đi tới {destination} ({start} - {end})",
        "budget_summary": "Tổng quan ngân sách",
        "flight_hotel_cost": "Chi phí máy bay + khách sạn",
        "daily_spending": "Chi tiêu hàng ngày ước tính (trong {days} ngày)",
        "total_cost": "Tổng chi phí ước tính",
        "your_budget": "Ngân sách của bạn",
        "under_budget": "Kế hoạch **tiết kiệm €{amount:,.2f}** so với ngân sách.",
        "over_budget": "Kế hoạch **vượt ngân sách €{amount:,.2f}**.",
        "status": "Tình trạng",
        "flight_info": "Thông tin chuyến bay",
        "airline": "Hãng bay",
        "total_price_people": "Tổng giá (cho {person} người)",
        "time": "Giờ",
        "details": "Chi tiết",
        "airport": "Sân bay",
        "depart": "Chiều đi",
        "return": "Chiều về",
        "total_journey": "Tổng hành trình",
        "layover": "Quá cảnh",
        "at": "tại",
        "arriving": "Hạ cánh",
        "other_flights": "Các lựa chọn khác từ Booking.com",
        "other_hotels": "Các khách sạn khác",
        "hotel_info": "Thông tin khách sạn",
        "rating": "Đánh giá",
        "based_on": "dựa trên {count} đánh giá",
        "taxes": "Thuế và phí",
        "total_price_stay": "Tổng giá (cho {nights} đêm, {person} người)",
        "location": "Vị trí",
        "on_maps": "trên Google Maps",
        "events": "Sự kiện trong thời gian lưu trú",
        "date": "Ngày",
        "event": "Sự kiện",
        "venue": "Địa điểm",
        "daily": "Lịch trình từng ngày",
        "no_activities": "Chưa có hoạt động cụ thể cho chuyến đi này.",
        "day": "Ngày {day}",
    },
}


def _report_language(state: TripState) -> str:
    raw = (state.get("language") or "en").strip().lower().replace("_", "-")
    if "-" in raw:
        raw = raw.split("-", 1)[0]
    return raw if raw in REPORT_LABELS else "en"


def _report_labels(language: str) -> dict:
    return REPORT_LABELS.get(language, REPORT_LABELS["en"])


def _format_report_date(date_str: str, language: str) -> str:
    dt_obj = datetime.strptime(date_str, "%Y-%m-%d")
    if language == "vi":
        return f"{dt_obj.day} {VI_MONTHS[dt_obj.month]} {dt_obj.year}"
    return dt_obj.strftime("%B %d, %Y")


def report_formattor_node(state: TripState) -> dict:
    """Takes the final trip plan and generates a richly formatted Markdown report with all details."""
    print("--- Report Formatter is running ---")
    itinerary = state.get("final_itinerary")
    trip_plan = state.get("trip_plan")
    evaluation = state.get("evaluation_result")
    events = state.get("events")
    map_html_content = state.get("map_html")
    language = _report_language(state)
    labels = _report_labels(language)
    
    if not itinerary or not trip_plan or not itinerary.selected_flight or not itinerary.selected_hotel:
        final_report_md = f"# {labels['failed_title']}\n\n"
        if not state.get("flight_options"):
            final_report_md += f"- {labels['no_flights']}\n"
        if not state.get("hotel_options"):
            final_report_md += f"- {labels['no_hotels']}\n"
        else:
            final_report_md += labels["failed_generic"]
        flight_list = format_flight_options_markdown(
            state.get("flight_options") or [],
            language,
        )
        hotel_list = format_hotel_options_markdown(
            state.get("hotel_options") or [],
            language,
            destination=getattr(trip_plan, "destination", None) if trip_plan else None,
            include_photos=False,
        )
        if flight_list:
            final_report_md += "\n\n" + flight_list + "\n"
        if hotel_list:
            final_report_md += "\n\n" + hotel_list + "\n"
    else:
        def format_duration(minutes: int) -> str:
            if not minutes: return ""
            hours, mins = divmod(minutes, 60)
            return f"{hours}h {mins}m"
            
        def format_date(date_str: str) -> str:
            return _format_report_date(date_str, language)

        md = (
            f"# {labels['title'].format(destination=trip_plan.destination, start=format_date(trip_plan.start_date), end=format_date(trip_plan.end_date))}\n\n"
        )
        
        md += f"## {labels['budget_summary']}\n"
        total_cost = evaluation.total_cost
        budget = trip_plan.budget

        flight_and_hotel_cost = itinerary.selected_flight.price + itinerary.selected_hotel.total_price
        total_daily_spending = total_cost - flight_and_hotel_cost

        md += f"- **{labels['flight_hotel_cost']}:** €{flight_and_hotel_cost:,.2f}\n"
        if total_daily_spending > 0:
            md += f"- **{labels['daily_spending'].format(days=trip_plan.days)}:** €{total_daily_spending:,.2f}\n"
        md += f"------------------------------------\n"
        md += f"- **{labels['total_cost']}:** €{total_cost:,.2f}\n"
        if budget is not None:
            md += f"- **{labels['your_budget']}:** €{budget:,.2f}\n\n"
            if total_cost <= budget:
                md += f"- **{labels['status']}:** {labels['under_budget'].format(amount=budget - total_cost)}\n\n"
            else:
                md += f"- **{labels['status']}:** {labels['over_budget'].format(amount=total_cost - budget)}\n\n"
        else:
            md += "\n"

        md += f"## {labels['flight_info']}\n"
        flight = itinerary.selected_flight
        dep_leg = flight.departure_leg
        ret_leg = flight.return_leg
        
        md += f"**{labels['airline']}:** {dep_leg.airline}\n"
        md += f"**{labels['total_price_people'].format(person=trip_plan.person)}:** €{flight.price:,.2f}\n\n"
        md += f"|  | {labels['time']} | {labels['details']} | {labels['airport']} |\n"
        md += "|:---|:---|:---|:---|\n"
        
        aircraft_dep = f"({dep_leg.aircraft_type})" if dep_leg.aircraft_type else ""
        details_depart = f"**{dep_leg.flight_number}** {aircraft_dep}"
        md += f"| **{labels['depart']}**<br>*{format_date(trip_plan.start_date)}* | **{dep_leg.departure_time}** | {details_depart} | **{dep_leg.departure_airport}** |\n"
        md += f"| | *{format_duration(dep_leg.duration_minutes)}* | {labels['total_journey']} | |\n"

        if dep_leg.is_layover:
            md += f"| | | *{format_duration(dep_leg.layover_duration_minutes)} {labels['layover']}* | *{labels['at']} {dep_leg.layover_airport}* |\n"
        md += f"| | **{dep_leg.arrival_time}** | {labels['arriving']} | **{dep_leg.arrival_airport}** |\n"
        md += "| | | | |\n"

        if ret_leg:
            aircraft_ret = f"({ret_leg.aircraft_type})" if ret_leg.aircraft_type else ""
            details_return = f"**{ret_leg.flight_number}** {aircraft_ret}"
            md += f"| **{labels['return']}**<br>*{format_date(trip_plan.end_date)}* | **{ret_leg.departure_time}** | {details_return} | **{ret_leg.departure_airport}** |\n"
            md += f"| | *{format_duration(ret_leg.duration_minutes)}* | {labels['total_journey']} | |\n"

            if ret_leg.is_layover:
                md += f"| | | *{format_duration(ret_leg.layover_duration_minutes)} {labels['layover']}* | *{labels['at']} {ret_leg.layover_airport}* |\n"
            md += f"| | **{ret_leg.arrival_time}** | {labels['arriving']} | **{ret_leg.arrival_airport}** |\n\n"
        else:
            md += "\n"

        other_flights = format_flight_options_markdown(
            [item for item in (state.get("flight_options") or []) if item != flight],
            language,
            limit=6,
            heading=False,
        )
        if other_flights:
            md += f"### {labels['other_flights']}\n{other_flights}\n\n"


        num_nights = (datetime.strptime(trip_plan.end_date, "%Y-%m-%d") - datetime.strptime(trip_plan.start_date, "%Y-%m-%d")).days
        hotel = itinerary.selected_hotel
        
        md += f"## {labels['hotel_info']}\n"
        
        photo_url = hotel.main_photo_url
        if photo_url and "square60" in photo_url:
            photo_url = photo_url.replace("square60", "max500")
            
        if photo_url:
            md += f"![{hotel.hotel_name}]({photo_url})\n\n"
            
        md += f"### {hotel.hotel_name}\n"
        md += f"**{labels['rating']}:** {hotel.rating} / 10.0 ({hotel.rating_word} {labels['based_on'].format(count=hotel.review_count)})\n"
        md += f"**{labels['taxes']}:** ~€{hotel.price_per_night:,.2f}\n" 
        md += f"**{labels['total_price_stay'].format(nights=num_nights, person=trip_plan.person)}:** €{hotel.total_price:,.2f}\n"
        
        google_maps_url = f"https://www.google.com/maps/search/?api=1&query={hotel.hotel_name.replace(' ', '+')}"
        md += f"- **{labels['location']}:** [{hotel.hotel_name} {labels['on_maps']}]({google_maps_url})\n\n"

        other_hotels = format_hotel_options_markdown(
            [
                item
                for item in (state.get("hotel_options") or [])
                if getattr(item, "hotel_name", None) != hotel.hotel_name
            ],
            language,
            limit=6,
            heading=False,
            include_photos=False,
        )
        if other_hotels:
            md += f"### {labels['other_hotels']}\n{other_hotels}\n\n"

        if events:
            md += f"---\n\n## {labels['events']}\n"
            event_list = format_event_options_markdown(events, language, heading=False)
            md += event_list + "\n\n"

        
        md += f"---\n\n## {labels['daily']}\n"
        if not itinerary.daily_plans:
            md += labels["no_activities"]
        else:
            start_date_obj = datetime.strptime(trip_plan.start_date, "%Y-%m-%d")
            activity_counter = 1
            for day_plan in itinerary.daily_plans:
                current_date = start_date_obj + timedelta(days=day_plan.day - 1)
                md += f"\n### {labels['day'].format(day=day_plan.day)} - {format_date(current_date.strftime('%Y-%m-%d'))}\n"
                for activity in day_plan.activities:
                    md += f"- **{activity.time_of_day}: {activity_counter}. {activity.name}**\n"
                    md += f"  - *{activity.description}*\n"
                
                    if activity.latitude and activity.longitude:
                        location_url = f"https://www.google.com/maps?q={activity.latitude},{activity.longitude}"
                        md += f"  - {labels['location']}: [{activity.name}]({location_url})\n"
                    else:
                        location_url = f"https://www.google.com/maps?q={activity.name.replace(' ', '+')}+{trip_plan.destination.replace(' ', '+')}"
                        md += f"  - {labels['location']}: [{activity.name}]({location_url})\n"
                
                    activity_counter += 1

        final_report_md = md

    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)
    md_path = os.path.join(output_dir, "trip_itinerary.md")
    html_path = os.path.join(output_dir, "trip_itinerary.html")

    try:
        with open(md_path, "w", encoding="utf-8") as f: f.write(final_report_md)
        print(f"-> Markdown report saved to: {md_path}")
        
        css_style = """<style> 
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #333; max-width: 800px; margin: 2rem auto; padding: 2rem; background: linear-gradient(to right, #f8f9fa, #ffffff); border: 1px solid #e1e1e1; box-shadow: 0 2px 8px rgba(0,0,0,0.05); border-radius: 8px; } 
            h1, h2, h3 { color: #2c3e50; border-bottom: 2px solid #f0f0f0; padding-bottom: 10px; } 
            h1 { font-size: 2.5em; text-align: center; } 
            h2 { font-size: 2em; } 
            code { background-color: #ecf0f1; padding: 2px 5px; border-radius: 4px; font-size: 0.9em; } 
            .map-container { margin-top: 30px; border-top: 2px solid #f0f0f0; padding-top: 20px; }
            iframe { width: 100%; height: 500px; border: none; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
        </style>"""

        html_body = markdown2.markdown(final_report_md, extras=["tables", "fenced-code-blocks"])

        full_html = f'<!DOCTYPE html><html lang="{language}"><head><meta charset="UTF-8"><title>AI Trip Plan</title>{css_style}</head><body>{html_body}</body></html>'
        with open(html_path, "w", encoding="utf-8") as f: f.write(full_html)
        print(f"-> HTML report saved to: {html_path}")
    except Exception as e:
        print(f"An error occurred while saving files: {e}")

    return {
        "markdown_report": final_report_md,
        "map_html": map_html_content 
    }