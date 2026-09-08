from typing import Optional

from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim

_geolocator = Nominatim(user_agent="ai_travel_agent_microservice_v2")
_geocode = RateLimiter(_geolocator.geocode, min_delay_seconds=2.0)


def nominatim_geocode(query: str) -> dict:
    print(f"--- Processing Geocoding Request: {query} ---")
    try:
        location = _geocode(query, timeout=15)
        if location:
            print(f"-> Found: {location.latitude}, {location.longitude}")
            return {
                "query": query,
                "latitude": location.latitude,
                "longitude": location.longitude,
                "address": location.address,
            }
        print("-> Location not found.")
        return {"query": query, "latitude": None, "longitude": None, "address": None}
    except Exception as e:
        print(f"Geocoding Internal Error: {e}")
        return {"query": query, "latitude": None, "longitude": None, "address": None}


def extract_queries(body) -> list:
    queries = []
    for item in body.existing_options or []:
        if isinstance(item, str) and item.strip():
            queries.append(item.strip())
            continue
        if isinstance(item, dict):
            query = item.get("query") or item.get("name")
            if query:
                dest = item.get("destination") or ""
                if dest and dest.lower() not in str(query).lower():
                    queries.append(f"{query}, {dest}")
                else:
                    queries.append(str(query).strip())
    if not queries and getattr(body.trip, "destination", None):
        queries.append(body.trip.destination)
    return queries
