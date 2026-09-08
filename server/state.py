from typing_extensions import TypedDict
from typing import Optional, List
from schemas import (
    TripRequest, FlightInfo, HotelInfo, Activity, EventInfo, 
    Itinerary, EvaluationResult
)

class TripState(TypedDict):
    user_request: str
    trip_plan: Optional[TripRequest]
    selected_flight: Optional[FlightInfo] 
    flight_options: List[FlightInfo] 
    selected_hotel: Optional[HotelInfo]
    hotel_options: List[HotelInfo]
    extracted_activities: Optional[List[Activity]]
    events: Optional[List[EventInfo]]
    final_itinerary: Optional[Itinerary]
    evaluation_result: Optional[EvaluationResult] 
    refinement_count: int 
    map_html: Optional[str]
    markdown_report: Optional[str]
    refresh: Optional[List[str]] # danh sách các trang cần refesh
    #
    language: Optional[str]
    user_feedback: Optional[str]
    user_id: Optional[str]
    session_id: Optional[str]
    memory_context: Optional[str]
    telemetry_run_id: Optional[str]
