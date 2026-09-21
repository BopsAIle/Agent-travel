"""Node gan toa do lat/lng cho tung hoat dong."""


import time

from app.core.telemetry import tracked_post
from app.graph.nodes.common import _call_agent_run, _refresh_targets
from app.core.config import (
    GEOCODING_AGENT_TIMEOUT,
    GEOCODING_FALLBACK_BUDGET,
    GEOCODING_SERVICE_URL,
)
from app.graph.state import TripState


# Tran thoi gian cho mot lan goi /geocode cua mot dia diem.
PER_PLACE_TIMEOUT = 4.0


def geocoding_agent(state: TripState) -> dict:
    """POST /agent/run on geocoding-service; fallback /geocode per activity.

    Ca hai duong deu bi chan boi ngan sach thoi gian: Nominatim cham hoac DNS hong
    lam geopy retry rat lau, truoc day node giu request toi ~7 phut. Hoat dong thieu
    toa do van dung duoc — report tu chuyen sang link tim kiem Google Maps.
    """
    print("--- Running Geocoding Agent ---")
    activities = state.get("extracted_activities")
    if not activities:
        return {}

    if "activities" not in _refresh_targets(state) and all(
        getattr(activity, "latitude", None) and getattr(activity, "longitude", None)
        for activity in activities
    ):
        print("-> Skipping geocoding (activities not in refresh).")
        return {}

    dest = state["trip_plan"].destination if state.get("trip_plan") else ""
    existing = []
    for activity in activities:
        name = getattr(activity, "name", None) or (activity.get("name") if isinstance(activity, dict) else "")
        existing.append({"name": name, "query": f"{name}, {dest}", "destination": dest})

    try:
        data = _call_agent_run(
            f"{GEOCODING_SERVICE_URL}/agent/run",
            state,
            task="search",
            existing_options=existing,
            timeout=GEOCODING_AGENT_TIMEOUT,
        )
        coords_by_query = {}
        coords_by_name = {}
        for item in data.get("options") or []:
            if not isinstance(item, dict):
                continue
            if item.get("query"):
                coords_by_query[str(item["query"]).lower()] = item
            if item.get("name"):
                coords_by_name[str(item["name"]).lower()] = item
        updated = []
        for activity in activities:
            name = getattr(activity, "name", "")
            query = f"{name}, {dest}"
            hit = coords_by_query.get(query.lower()) or coords_by_name.get(name.lower())
            if hit and hit.get("latitude") and hit.get("longitude"):
                activity.latitude = hit["latitude"]
                activity.longitude = hit["longitude"]
                print(f"-> Geocoded: {name}")
            updated.append(activity)
        print(f"-> Geocoding reasoning: {data.get('reasoning')}")
        print(f"-> Geocoding memory_hits: {data.get('memory_hits')}")
        return {"extracted_activities": updated}
    except Exception as exc:
        print(f"-> Geocoding /agent/run failed, fallback /geocode: {exc}")

    # Ngan sach rieng cho duong du phong: luot agent vua roi co the da dung het phan
    # cua no, nhung van dang thu tung dia diem trong mot khoang ngan.
    deadline = time.monotonic() + GEOCODING_FALLBACK_BUDGET
    updated_activities = []
    skipped = 0
    for activity in activities:
        remaining = deadline - time.monotonic()
        if remaining <= 0.5:
            skipped += 1
            updated_activities.append(activity)
            continue
        search_query = f"{activity.name}, {dest}"
        try:
            response = tracked_post(
                f"{GEOCODING_SERVICE_URL}/geocode",
                json={"query": search_query},
                timeout=max(1.0, min(remaining, PER_PLACE_TIMEOUT)),
            )
            if response.status_code == 200:
                payload = response.json()
                if payload.get("latitude") and payload.get("longitude"):
                    activity.latitude = payload["latitude"]
                    activity.longitude = payload["longitude"]
                    print(f"-> Geocoded: {activity.name}")
        except Exception as inner:
            print(f"-> Error geocoding {activity.name}: {inner}")
        updated_activities.append(activity)
    if skipped:
        print(f"-> Geocoding budget exceeded; {skipped} place(s) left without coordinates.")
    return {"extracted_activities": updated_activities}
