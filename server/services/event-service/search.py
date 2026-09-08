import os
from typing import List

import requests
from fastapi import HTTPException

from schemas import EventInfo


def fetch_events(city: str, start_date: str, end_date: str) -> List[EventInfo]:
    print(f"--- Processing Event Search for {city} ---")
    api_key = os.getenv("TICKETMASTER_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="TICKETMASTER_API_KEY missing")

    start_datetime = f"{start_date}T00:00:00Z"
    end_datetime = f"{end_date}T23:59:59Z"
    url = "https://app.ticketmaster.com/discovery/v2/events.json"
    params = {
        "apikey": api_key,
        "city": city,
        "startDateTime": start_datetime,
        "endDateTime": end_datetime,
        "sort": "relevance,desc",
        "size": 50,
    }
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        if not data.get("_embedded") or not data["_embedded"].get("events"):
            print(f"-> No events found in {city}.")
            return []

        events = []
        for event_data in data["_embedded"]["events"]:
            venue_info = event_data.get("_embedded", {}).get("venues", [{}])[0]
            local_date = event_data.get("dates", {}).get("start", {}).get("localDate", "")
            events.append(
                EventInfo(
                    name=event_data.get("name", "Unknown Event"),
                    date=local_date,
                    venue=venue_info.get("name", "Venue details not available"),
                    url=event_data.get("url", "#"),
                )
            )
        print(f"-> Found {len(events)} events.")
        return events
    except Exception as e:
        print(f"Ticketmaster API Error: {e}")
        return []
