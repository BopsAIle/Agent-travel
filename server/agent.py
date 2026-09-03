from langgraph.graph import StateGraph, START, END
from state import TripState
from nodes import (
    planner_agent,
    flight_agent,
    hotel_agent,
    event_agent,
    data_aggregator_agent,
    activity_extraction_agent,
    geocoding_agent,
    activity_scheduling_agent,
    evaluator_agent,
    map_generator_node,
    report_formattor_node,
    should_refine_or_end
)
from telemetry import timed_node


workflow = StateGraph(TripState)

workflow.add_node("planner", timed_node("planner", planner_agent))
workflow.add_node("flight_agent", timed_node("flight_agent", flight_agent))
workflow.add_node("hotel_agent", timed_node("hotel_agent", hotel_agent))
workflow.add_node("event_agent", timed_node("event_agent", event_agent))
workflow.add_node("aggregator", timed_node("aggregator", data_aggregator_agent))
workflow.add_node("activity_extractor", timed_node("activity_extractor", activity_extraction_agent))
workflow.add_node("geocoding_agent", timed_node("geocoding_agent", geocoding_agent))
workflow.add_node("scheduler", timed_node("scheduler", activity_scheduling_agent))
workflow.add_node("evaluator", timed_node("evaluator", evaluator_agent))
workflow.add_node("map_generator", timed_node("map_generator", map_generator_node))
workflow.add_node("report_formatter", timed_node("report_formatter", report_formattor_node))


workflow.add_edge(START, "planner")

workflow.add_edge("planner", "flight_agent")
workflow.add_edge("planner", "hotel_agent")
workflow.add_edge("planner", "event_agent")

workflow.add_edge("flight_agent", "aggregator")
workflow.add_edge("hotel_agent", "aggregator")
workflow.add_edge("event_agent", "aggregator")

workflow.add_edge("aggregator", "activity_extractor")

workflow.add_edge("activity_extractor", "geocoding_agent")

workflow.add_edge("geocoding_agent", "scheduler")

workflow.add_edge("scheduler", "evaluator")


workflow.add_conditional_edges(
    "evaluator",
    should_refine_or_end,
    {
        "end": "map_generator",         
        "refine_flight": "flight_agent", 
        "refine_hotel": "hotel_agent"    
    }
)

workflow.add_edge("map_generator", "report_formatter")
workflow.add_edge("report_formatter", END)

app = workflow.compile()