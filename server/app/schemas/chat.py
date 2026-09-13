"""Schema cua mot luot hoi thoai va cac request tra cuu dia diem."""

from app.schemas.trip import PartialTripRequest
from pydantic import BaseModel, Field
from typing import List, Literal, Optional


LOOKUP_TARGETS = ("flight", "hotel", "event", "activity")

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

class ChatRequest(BaseModel):
    message: str = Field(description="The user's chat message.")
    session_id: Optional[str] = Field(default=None, description="Existing chat session id, if any.")

class RestoreChatRequest(BaseModel):
    messages: List[dict] = Field(default_factory=list)
    slots: dict = Field(default_factory=dict)
    language: Optional[str] = None
    has_plan: bool = False
