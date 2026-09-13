from typing import List, Optional, Literal
from datetime import datetime
from pydantic import BaseModel, Field


REQUIRED_TRIP_FIELDS = ("origin", "destination", "start_date", "end_date", "person")
LOOKUP_TARGETS = ("flight", "hotel", "event", "activity")

## TripRequest này lưu trữ đầu vào của user, phải khai báo các schemas có description rõ ràng để
# trích xuất ra các fields 
class TripRequest(BaseModel):
    """Schema for user's travel requests."""
    origin: str = Field(description="The departure city for the trip.")
    destination: str = Field(description="The arrival city for the trip.")
    start_date: str = Field(description="The start date of the trip in YYYY-MM-DD format.")
    end_date: str = Field(description="The end date of the trip in YYYY-MM-DD format.")
    person: int = Field(description="The total number of people participating in the trip.")
    budget: Optional[float] = Field(default=None, description="The estimated budget for the trip.")
    interests: Optional[List[str]] = Field(default=None, description="A list of interests for the trip, e.g., ['art', 'history', 'food'].")
    daily_spending_budget: Optional[float] = Field(default=None, description="The estimated daily spending budget per person for activities, food, etc.")

    @property
    def days(self) -> int:
        start = datetime.strptime(self.start_date, "%Y-%m-%d")
        end = datetime.strptime(self.end_date, "%Y-%m-%d")
        return (end - start).days + 1


class FlightLeg(BaseModel):
    """Schema for a single leg of a flight (either departure or return)."""
    departure_time: str = Field(description="Departure time in HH:MM format.")
    arrival_time: str = Field(description="Arrival time in HH:MM format.")
    departure_airport: str = Field(description="Full name and IATA code of the departure airport.")
    arrival_airport: str = Field(description="Full name and IATA code of the arrival airport.")
    duration_minutes: int = Field(description="Duration of this specific leg in minutes.")
    airline: str = Field(description="The name of the airline for this leg.")
    flight_number: str = Field(description="The flight number, e.g., 'TK1857'.")
    aircraft_type: str = Field(description="The type of aircraft, e.g., 'Boeing 737'.")
    is_layover: bool = Field(default=False, description="True if this journey has a layover.")
    layover_airport: Optional[str] = Field(default=None, description="The airport where the layover occurs.")
    layover_duration_minutes: Optional[int] = Field(default=None, description="The duration of the layover in minutes.")

class FlightInfo(BaseModel):
    """Schema for flight information, now with detailed legs."""
    price: float = Field(description="The total price of the flight for all passengers.")
    departure_leg: FlightLeg
    return_leg: Optional[FlightLeg] = Field(
        default=None,
        description="Return leg for round-trip. Omitted for one-way searches.",
    )
    total_duration_minutes: int = Field(description="The total duration in minutes.")

class FlightSelection(BaseModel):
    """Schema for the selected flight."""
    best_option_index: int = Field(description="The index (starting from 0) of the best flight option from the provided list.")
    reasoning: str = Field(description="A brief explanation of why this option was chosen.")


class HotelInfo(BaseModel):
    """Schema for hotel information."""
    hotel_name: str = Field(description="The name of the hotel.")
    price_per_night: float = Field(description="The price per night.")
    total_price: float = Field(description="The total price for the entire stay.")
    rating: float = Field(description="The hotel's rating out of 9.")
    review_count: int = Field(description="Total number of reviews for the hotel.")
    rating_word: str = Field(description="The rating described as a word, e.g., 'Exceptional'.")
    main_photo_url: Optional[str] = Field(default=None, description="URL of the hotel's main photo.")
    static_map_url: Optional[str] = Field(default=None, description="URL of a static map image showing the hotel's location.")

class HotelSelection(BaseModel):
    """Schema for the selected hotel."""
    best_option_index: int = Field(description="The index (starting from 0) of the best hotel option from the provided list.")
    reasoning: str = Field(description="A brief explanation of why this hotel was chosen, balancing price and rating.")


class Activity(BaseModel):
    """Schema for a single activity."""
    name: str = Field(description="Name of the activity or place. ASCII letters only; no apostrophes or quotes.")
    description: str = Field(description="A brief description of the activity, max 15 words. No apostrophes or quotes.")
    location: str = Field(description="Location or address of the activity.")
    time_of_day: str = Field(description="Suggested time of day, e.g., 'Morning', 'Afternoon', 'Evening'.")
    latitude: Optional[float] = Field(default=None, description="The latitude of the activity location.")
    longitude: Optional[float] = Field(default=None, description="The longitude of the activity location.")

class ExtractedActivities(BaseModel):
    activities: List[Activity] = Field(
        description="At most 8 iconic physical places. Prefer quality over quantity.",
    )

class DailyPlan(BaseModel):
    day: int = Field(description="The day number (e.g., 1, 2, 3).")
    activities: List[Activity] = Field(description="A list of activities for the day.")

class ScheduledActivities(BaseModel):
    daily_plans: List[DailyPlan]

class EventInfo(BaseModel):
    name: str = Field(description="The name of the event.")
    date: str = Field(description="The date of the event in YYYY-MM-DD format.")
    venue: str = Field(description="The name of the venue where the event is held.")
    url: str = Field(description="A direct URL to the event page for more details and tickets.")

class SelectedEvents(BaseModel):
    events: List[EventInfo]


class Itinerary(BaseModel):
    """The complete, final itinerary for the trip."""
    selected_flight: FlightInfo
    selected_hotel: HotelInfo
    daily_plans: List[DailyPlan]

class EvaluationResult(BaseModel):
    """Schema for the evaluation result."""
    action: Literal["APPROVE", "REFINE_HOTEL", "REFINE_FLIGHT"] = Field(description="Action to take.")
    feedback: str = Field(description="Feedback on the plan, explaining the reason for the action.")
    total_cost: float = Field(description="The calculated total cost of the trip.")


class PartialTripRequest(BaseModel):
    """Incomplete trip details extracted from a chat turn. Omit fields the user did not mention."""
    origin: Optional[str] = Field(default=None, description="Departure city, if mentioned.")
    destination: Optional[str] = Field(default=None, description="Arrival city, if mentioned.")
    start_date: Optional[str] = Field(default=None, description="Start date in YYYY-MM-DD, if mentioned.")
    end_date: Optional[str] = Field(default=None, description="End date in YYYY-MM-DD, if mentioned.")
    person: Optional[int] = Field(default=None, description="Number of travelers, if mentioned.")
    budget: Optional[float] = Field(default=None, description="Total budget amount, if mentioned.")
    interests: Optional[List[str]] = Field(default=None, description="Interests, if mentioned.")
    daily_spending_budget: Optional[float] = Field(
        default=None,
        description="Daily spending budget per person, if mentioned.",
    )


class PlaceBrief(BaseModel):
    """Grounded visitor brief for one physical place. Keep every field short and unique."""

    name: str = Field(max_length=160, description="Official place name. Max 12 words.")
    address: str = Field(default="", max_length=240, description="Street or area. Max 20 words. Unknown if missing.")
    why_visit: str = Field(max_length=500, description="2-3 sentences for a traveler. Max 70 words. No repeated phrases.")
    highlights: List[str] = Field(
        default_factory=list,
        description="3-5 short visitor highlights. Each item max 18 words.",
    )
    hours_or_tips: str = Field(
        default="",
        max_length=280,
        description="Hours, tickets, or one practical tip. Max 35 words. Unknown if missing.",
    )
    how_to_get_there: str = Field(
        default="",
        max_length=280,
        description="How to reach it. Max 35 words. Unknown if missing.",
    )
    good_for: str = Field(
        default="",
        max_length=160,
        description="Best time of day or who it suits. Max 18 words.",
    )


class PlaceQualityCheck(BaseModel):
    """Critic verdict on a drafted place answer."""

    ok: bool = Field(description="True if the draft is usable for the traveler.")
    verdict: Literal["approve", "retry", "fallback"] = Field(
        description="approve=send it; retry=regenerate with notes; fallback=use the template."
    )
    issues: List[str] = Field(
        default_factory=list,
        description="Short issues: repetition, wrong place, invented hours, empty, off-topic.",
    )


class ConversationTurn(BaseModel):
    """One conversational reply plus structured extraction for the travel agent."""
    reply: str = Field(
        description=(
            "Assistant reply in the user's language, always in markdown. "
            "Chat/recall/refine: start with a short bold title when giving advice, then bullets "
            "(one tip per line). Numbered cards for choices: bold name and price on the first line, "
            "then indented bullets. Never put a whole option on one long line. "
            "If intent is place or lookup, write only one short acknowledgement such as "
            "'Let me look that up.' Do not invent prices, times, lists, or place details here."
        )
    )
    detected_language: str = Field(
        description="Short language code of the latest user message, e.g. vi, en, fr, ja."
    )
    origin: Optional[str] = Field(default=None, description="Departure city, if mentioned this turn.")
    destination: Optional[str] = Field(default=None, description="Arrival city, if mentioned this turn.")
    start_date: Optional[str] = Field(default=None, description="Start date in YYYY-MM-DD, if mentioned this turn.")
    end_date: Optional[str] = Field(default=None, description="End date in YYYY-MM-DD, if mentioned this turn.")
    person: Optional[int] = Field(default=None, description="Number of travelers, if mentioned this turn.")
    budget: Optional[float] = Field(default=None, description="Total budget amount, if mentioned this turn.")
    interests: Optional[List[str]] = Field(default=None, description="Interests, if mentioned this turn.")
    daily_spending_budget: Optional[float] = Field(
        default=None,
        description="Daily spending budget per person, if mentioned this turn.",
    )
    place_index: Optional[int] = Field(
        default=None,
        description="1-based itinerary index when the user asks about location 5 / địa điểm số 5.",
    )
    place_query: Optional[str] = Field(
        default=None,
        description="Place name if the user asked about a specific attraction by name.",
    )
    intent: Literal["chat", "plan", "refine", "recall", "place", "lookup"] = Field(
        description=(
            "chat = keep talking; plan = create a full itinerary; "
            "refine = edit an existing plan; recall = answer from traveler memory; "
            "place = look up details for a numbered or named itinerary place; "
            "lookup = search one capability (flights, hotels, events, or activities) "
            "with whatever fields the user already gave."
        )
    )
    lookup_targets: List[Literal["flight", "hotel", "event", "activity", "activities"]] = Field(
        default_factory=list,
        description=(
            "Which services to query when intent is lookup. "
            "Example: ['flight'] to list flights, ['activity'] for things to do. "
            "Empty when intent is not lookup."
        ),
    )
    refine_targets: List[Literal["flight", "hotel", "activities", "dates", "destination", "budget", "full"]] = Field(
        default_factory=list,
        description="What to refresh when intent is refine. Empty when intent is chat.",
    )
    ready_to_plan: bool = Field(
        default=False,
        description="True when required trip fields are known and it is appropriate to run the planner.",
    )

    def to_extracted(self) -> "PartialTripRequest":
        return PartialTripRequest(
            origin=self.origin,
            destination=self.destination,
            start_date=self.start_date,
            end_date=self.end_date,
            person=self.person,
            budget=self.budget,
            interests=self.interests,
            daily_spending_budget=self.daily_spending_budget,
        )


class ProfilePatch(BaseModel):
    """Durable traveler preferences. Only fill fields that are newly stated or clearly changed."""

    home_city: Optional[str] = Field(default=None, description="Usual departure / home city.")
    preferred_language: Optional[str] = Field(default=None, description="Preferred language code, e.g. vi or en.")
    budget_pref: Optional[float] = Field(default=None, description="Typical overall trip budget if the user stated a lasting preference.")
    interests: Optional[List[str]] = Field(default=None, description="Standing interests, not one-off trip activities.")
    dietary: Optional[str] = Field(default=None, description="Dietary needs or restrictions.")
    hotel_style: Optional[str] = Field(default=None, description="Preferred hotel style, e.g. boutique, luxury, budget.")
    travel_pace: Optional[str] = Field(default=None, description="Preferred pace, e.g. relaxed, packed.")


class MemoryExtraction(BaseModel):
    """Facts to store in long-term memory. Omit anything that is only true for the current trip."""

    profile: Optional[ProfilePatch] = Field(default=None, description="Profile fields to create or update.")
    facts: List[str] = Field(
        default_factory=list,
        description="Short durable facts, e.g. 'allergic to peanuts', 'hates overnight flights'. Empty if none.",
    )


class ChatRequest(BaseModel):
    message: str = Field(description="The user's chat message.")
    session_id: Optional[str] = Field(default=None, description="Existing chat session id, if any.")


class AuthRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str


class RestoreChatRequest(BaseModel):
    messages: List[dict] = Field(default_factory=list)
    slots: dict = Field(default_factory=dict)
    language: Optional[str] = None
    has_plan: bool = False