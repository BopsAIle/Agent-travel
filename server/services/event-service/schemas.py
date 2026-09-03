from pydantic import BaseModel, Field

class EventSearchRequest(BaseModel):
    city: str
    start_date: str
    end_date: str

class EventInfo(BaseModel):
    """Schema for a single event."""
    name: str = Field(description="The name of the event.")
    date: str = Field(description="The date of the event.")
    venue: str = Field(description="The name of the venue.")
    url: str = Field(description="A direct URL to the event page.")