"""Toan bo schema Pydantic dung chung. Import truc tiep tu app.schemas."""

from app.schemas.trip import (
    Activity,
    DailyPlan,
    EvaluationResult,
    EventInfo,
    ExtractedActivities,
    FlightInfo,
    FlightLeg,
    FlightSelection,
    HotelInfo,
    HotelSelection,
    Itinerary,
    PartialTripRequest,
    REQUIRED_TRIP_FIELDS,
    ScheduledActivities,
    SelectedEvents,
    TripRequest,
)
from app.schemas.chat import (
    ChatRequest,
    ConversationTurn,
    LOOKUP_TARGETS,
    PlaceBrief,
    PlaceQualityCheck,
    RestoreChatRequest,
)
from app.schemas.auth import AuthRequest, AuthResponse
from app.schemas.memory import MemoryExtraction, ProfilePatch

__all__ = [
    "Activity",
    "AuthRequest",
    "AuthResponse",
    "ChatRequest",
    "ConversationTurn",
    "DailyPlan",
    "EvaluationResult",
    "EventInfo",
    "ExtractedActivities",
    "FlightInfo",
    "FlightLeg",
    "FlightSelection",
    "HotelInfo",
    "HotelSelection",
    "Itinerary",
    "LOOKUP_TARGETS",
    "MemoryExtraction",
    "PartialTripRequest",
    "PlaceBrief",
    "PlaceQualityCheck",
    "ProfilePatch",
    "REQUIRED_TRIP_FIELDS",
    "RestoreChatRequest",
    "ScheduledActivities",
    "SelectedEvents",
    "TripRequest",
]
