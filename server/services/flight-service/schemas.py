from typing import List, Optional, Literal
from datetime import datetime
from pydantic import BaseModel, Field


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
    price: float = Field(description="The total price of the round-trip flight for all passengers.")
    departure_leg: FlightLeg
    return_leg: FlightLeg
    total_duration_minutes: int = Field(description="The total round-trip duration in minutes.")

