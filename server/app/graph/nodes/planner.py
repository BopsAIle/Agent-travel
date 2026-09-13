"""Node planner: bien yeu cau tho cua user thanh TripRequest."""


from app.core.llm import llm, openai_model
from app.core.telemetry import tracked_invoke
from app.graph.nodes.common import _trip_plan_is_complete
from app.graph.state import TripState
from app.schemas import TripRequest
from datetime import datetime


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
