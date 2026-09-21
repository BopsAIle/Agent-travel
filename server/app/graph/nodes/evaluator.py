"""Node doi chieu chi phi voi ngan sach va dinh tuyen refine."""


from app.core.llm import llm_gemini
from app.core.telemetry import tracked_invoke
from app.domain.planning_issues import collect_planning_issues
from app.graph.state import TripState
from app.schemas import EvaluationResult


def evaluator_agent(state: TripState) -> dict:
    print("--- Running Smart Evaluator Agent (High IQ Mode) ---")
    trip_plan = state['trip_plan']
    selected_flight = state['selected_flight']
    selected_hotel = state['selected_hotel']
    flight_options = state['flight_options']
    hotel_options = state['hotel_options']
    refinement_count = state.get('refinement_count', 0)
    
    if not selected_flight or not selected_hotel:
        issues = collect_planning_issues(state)
        return {
            "evaluation_result": EvaluationResult(
                action="INCOMPLETE",
                feedback=" ".join(issues),
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

    if action == "INCOMPLETE":
        print("-> Plan is incomplete because required provider data is missing.")
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
