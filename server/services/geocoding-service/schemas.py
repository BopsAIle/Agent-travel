from typing import Optional
from pydantic import BaseModel

class GeocodeRequest(BaseModel):
    query: str  

class GeocodeResponse(BaseModel):
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address: Optional[str] = None