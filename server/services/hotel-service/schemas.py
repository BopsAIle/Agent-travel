from typing import List, Optional, Literal
from datetime import datetime
from pydantic import BaseModel, Field

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

