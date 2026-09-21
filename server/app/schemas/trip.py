"""Schema mo ta chuyen di: yeu cau, ve, khach san, hoat dong, lich trinh."""

from datetime import date, datetime
from pydantic import BaseModel, Field
from typing import List, Literal, Optional


REQUIRED_TRIP_FIELDS = ("origin", "destination", "start_date", "end_date", "person")

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
    action: Literal["APPROVE", "REFINE_HOTEL", "REFINE_FLIGHT", "INCOMPLETE"] = Field(description="Action to take.")
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
