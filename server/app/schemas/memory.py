"""Schema trich xuat ho so va su kien ghi nho ve nguoi dung."""

from pydantic import BaseModel, Field
from typing import List, Optional


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
