from typing import List, Optional

from pydantic import BaseModel, Field


class ActivitySearchRequest(BaseModel):
    destination: str
    interests: List[str]


class PlaceDetailRequest(BaseModel):
    place_name: str
    destination: str = ""


class PlaceSnippet(BaseModel):
    title: str = ""
    url: str = ""
    content: str = ""


class PlaceDetailResponse(BaseModel):
    place_name: str
    destination: str = ""
    results: List[PlaceSnippet] = Field(default_factory=list)
