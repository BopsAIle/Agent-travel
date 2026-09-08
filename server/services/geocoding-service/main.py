import sys
from pathlib import Path

_SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVER_ROOT))

from fastapi import FastAPI
from packages.agent_runtime import agent_service_lifespan
from schemas import GeocodeRequest, GeocodeResponse
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(lifespan=agent_service_lifespan)

Instrumentator().instrument(app).expose(app)

@app.post("/geocode", response_model=GeocodeResponse)
def geocode_location(request: GeocodeRequest):
    print(f"--- Processing Geocoding Request: {request.query} ---")
    try:
        geolocator = Nominatim(user_agent="ai_travel_agent_microservice_v2")
        
        geocode = RateLimiter(geolocator.geocode, min_delay_seconds=2.0)

        location = geocode(request.query, timeout=15)
        
        
        if location:
            print(f"-> Found: {location.latitude}, {location.longitude}")
            return GeocodeResponse(
                latitude=location.latitude, 
                longitude=location.longitude,
                address=location.address
            )
        else:
            print("-> Location not found.")
            return GeocodeResponse(latitude=None, longitude=None, address=None)
            
    except Exception as e:
        print(f"Geocoding Internal Error: {e}")
        return GeocodeResponse(latitude=None, longitude=None, address=None)