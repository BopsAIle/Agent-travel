import os
import requests
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from schemas import HotelInfo
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI()

Instrumentator().instrument(app).expose(app)

class HotelSearchRequest(BaseModel):
    destination: str
    start_date: str
    end_date: str
    person: int

def find_location_id(city_name: str) -> Optional[str]:
    print(f"--- Finding Location ID for {city_name} ---")
    url = "https://booking-com18.p.rapidapi.com/stays/auto-complete"
    querystring = {"query": city_name}
    headers = {
        "x-rapidapi-key": os.getenv("RAPIDAPI_KEY"),
        "x-rapidapi-host": "booking-com18.p.rapidapi.com"
    }
    try:
        response = requests.get(url, headers=headers, params=querystring)
        response.raise_for_status()
        data = response.json()
        if data.get('data') and len(data['data']) > 0:
            return data['data'][0].get('id')
        return None
    except Exception as e:
        print(f"Location ID Error: {e}")
        return None

@app.post("/search", response_model=List[HotelInfo])
def search_hotels(request: HotelSearchRequest):
    print(f"Processing hotel search for: {request.destination}")
    
    location_id = find_location_id(request.destination)
    if not location_id:
        print("Location ID not found.")
        return []

    print(f"Searching hotels with ID: {location_id}")
    url = "https://booking-com18.p.rapidapi.com/stays/search"
    querystring = {
        "locationId": location_id,
        "checkinDate": request.start_date,
        "checkoutDate": request.end_date,
        "adults": str(request.person),
        "sortBy": "bayesian_review_score", 
        "currencyCode": "EUR"
    }
    headers = {
        "x-rapidapi-key": os.getenv("RAPIDAPI_KEY"),
        "x-rapidapi-host": "booking-com18.p.rapidapi.com"
    }

    try:
        response = requests.get(url, headers=headers, params=querystring)
        response.raise_for_status()
        data = response.json()

        if not data.get('data'):
            return []

        results = []
        for hotel_data in data.get('data', [])[:10]:
            price_breakdown = hotel_data.get('priceBreakdown', {})
            total_price = price_breakdown.get('grossPrice', {}).get('value', 0)
            price_per_night = price_breakdown.get('excludedPrice', {}).get('value', 0)
            
            photo_url = None
            if hotel_data.get('photoUrls'):
                photo_url = hotel_data['photoUrls'][0]

            static_map_url = None
            lat = hotel_data.get('latitude')
            lon = hotel_data.get('longitude')
            if lat and lon:
                static_map_url = f"https://staticmap.openstreetmap.de/staticmap.php?center={lat},{lon}&zoom=15&size=600x300&marker={lat},{lon},red-pushpin"
            
            results.append(
                HotelInfo(
                    hotel_name=hotel_data.get('name', 'Unknown Hotel'),
                    price_per_night=round(price_per_night, 2),
                    total_price=total_price,
                    rating=hotel_data.get('reviewScore', 0),
                    review_count=hotel_data.get('reviewCount', 0),
                    rating_word=hotel_data.get('reviewScoreWord', ''),
                    main_photo_url=photo_url,
                    static_map_url=static_map_url
                )
            )
        
        print(f"Found {len(results)} hotels.")
        return results

    except Exception as e:
        print(f"Hotel API Error: {e}")
        return []