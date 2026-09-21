from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class TripPayload(BaseModel):
    """Subset of a trip plan that an agent-service needs to do its job."""

    model_config = ConfigDict(extra="ignore")

    origin: Optional[str] = None
    destination: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    person: Optional[int] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    # Tuoi tre em da kiem chung voi nha cung cap; rong nghia la CHUA biet tuoi.
    # Khong bao gio bia tuoi: Booking.com tra 0 ket qua voi tre duoi 2 tuoi.
    child_ages: Optional[List[int]] = None
    budget: Optional[float] = None
    interests: Optional[List[str]] = None
    hard_constraints: Optional[List[str]] = None
    soft_preferences: Optional[List[str]] = None
    priorities: Optional[List[str]] = None


class AgentRunRequest(BaseModel):
    """POST /agent/run body — same shape for every agent-service."""

    model_config = ConfigDict(extra="ignore")

    user_id: str
    session_id: str
    task: Literal["search", "refine"] = "search"
    trip: TripPayload = Field(default_factory=TripPayload)
    traveler_context: str = ""
    feedback: str = ""
    existing_options: List[Any] = Field(default_factory=list)


class AgentRunResponse(BaseModel):
    """POST /agent/run result — options plus the agent's pick."""

    model_config = ConfigDict(extra="ignore")

    options: List[Any] = Field(default_factory=list)
    selected: Optional[Any] = None
    reasoning: str = ""
    memory_hits: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
