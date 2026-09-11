import json
import os
import re
import unicodedata
import concurrent.futures
from datetime import datetime
from typing import Any, List, Optional

import requests

from schemas import FlightInfo, FlightLeg

_IATA_TOKEN = re.compile(r"^[A-Za-z]{3}$")
KNOWN_IATA = {
    "singapore": ["SIN"],
    "singapo": ["SIN"],
    "hanoi": ["HAN"],
    "ha noi": ["HAN"],
    "ho chi minh": ["SGN"],
    "hochiminh": ["SGN"],
    "saigon": ["SGN"],
    "sai gon": ["SGN"],
    "danang": ["DAD"],
    "da nang": ["DAD"],
    "phu quoc": ["PQC"],
    "nha trang": ["CXR"],
    "hue": ["HUI"],
    "can tho": ["VCA"],
    "hai phong": ["HPH"],
    "hong kong": ["HKG"],
    "hongkong": ["HKG"],
    "bangkok": ["BKK", "DMK"],
    "kuala lumpur": ["KUL"],
    "tokyo": ["HND", "NRT"],
    "osaka": ["KIX", "ITM"],
    "seoul": ["ICN", "GMP"],
    "taipei": ["TPE"],
    "beijing": ["PEK", "PKX"],
    "shanghai": ["PVG", "SHA"],
    "guangzhou": ["CAN"],
    "paris": ["CDG", "ORY"],
    "london": ["LHR", "LGW", "STN", "LTN"],
    "new york": ["JFK", "EWR", "LGA"],
    "nyc": ["JFK", "EWR", "LGA"],
    "los angeles": ["LAX"],
    "san francisco": ["SFO"],
    "sydney": ["SYD"],
    "melbourne": ["MEL"],
}


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text or "")
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn").lower()


def _fallback_iata(city_name: str) -> List[str]:
    raw = (city_name or "").strip()
    if _IATA_TOKEN.fullmatch(raw):
        return [raw.upper()]
    folded = re.sub(r"[^a-z0-9\s]", " ", _fold(raw))
    folded = re.sub(r"\s+", " ", folded).strip()
    if folded in KNOWN_IATA:
        return list(KNOWN_IATA[folded])
    for key, codes in KNOWN_IATA.items():
        if key in folded or folded in key:
            return list(codes)
    return []


def _as_dict(payload: Any) -> dict:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _locations_from_payload(data: dict) -> list:
    raw = data.get("data")
    if isinstance(raw, dict):
        raw = (
            raw.get("airports")
            or raw.get("AIRPORT")
            or raw.get("destinations")
            or raw.get("result")
            or []
        )
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = []
    return raw if isinstance(raw, list) else []


def _code_from_location(location: Any) -> Optional[str]:
    if isinstance(location, str):
        text = location.strip()
        if _IATA_TOKEN.fullmatch(text):
            return text.upper()
        match = re.search(r"\b([A-Z]{3})(?:\.AIRPORT|\.CITY)?\b", text.upper())
        return match.group(1) if match else None
    if not isinstance(location, dict):
        return None
    for key in ("code", "iataCode", "iata", "airportCode"):
        value = location.get(key)
        if isinstance(value, str) and _IATA_TOKEN.fullmatch(value.strip()):
            return value.strip().upper()
    ident = str(location.get("id") or "")
    match = re.match(r"^([A-Z]{3})\.(AIRPORT|CITY)", ident.upper())
    return match.group(1) if match else None


def find_iata_codes(city_name: str) -> List[str]:
    """Resolve a city name to IATA codes; fall back to a known map if Booking.com fails."""
    fallback = _fallback_iata(city_name)
    if _IATA_TOKEN.fullmatch((city_name or "").strip()):
        return fallback
    print(f"--- Calling Booking.com auto-complete API for {city_name} ---")
    url = "https://booking-com18.p.rapidapi.com/flights/v2/auto-complete"
    querystring = {"query": city_name}
    headers = {
        "x-rapidapi-key": (os.getenv("RAPIDAPI_KEY") or "").strip(),
        "x-rapidapi-host": "booking-com18.p.rapidapi.com",
    }
    try:
        response = requests.get(url, headers=headers, params=querystring, timeout=20)
        response.raise_for_status()
        data = _as_dict(response.json())
        airports: List[str] = []
        others: List[str] = []
        for location in _locations_from_payload(data):
            code = _code_from_location(location)
            if not code:
                continue
            loc_type = ""
            if isinstance(location, dict):
                loc_type = str(location.get("type") or location.get("placeType") or "").upper()
            if "AIRPORT" in loc_type:
                airports.append(code)
            else:
                others.append(code)
        codes = list(dict.fromkeys(airports or others or fallback))
        if not codes:
            codes = fallback
        print(f"-> IATA for {city_name}: {codes}")
        return codes
    except Exception as e:
        print(f"Error finding IATA for {city_name}: {e}; fallback={fallback}")
        return fallback

"""
parse_journey_segment đổi một chặng bay thô từ Booking.com thành FlightLeg — object nội bộ mà agent và API dùng được.
 JSON API thì lộn xộn, thiếu field, nested sâu;
 hàm này lọc ra thông tin cần thiết hoặc trả None nếu không parse được.
"""
def parse_journey_segment(segment: dict) -> Optional[FlightLeg]:
    try:
        legs = segment.get("legs", [])
        if not legs:
            return None

        departure_airport_info = segment.get("departureAirport")
        arrival_airport_info = segment.get("arrivalAirport")
        total_duration_minutes = segment.get("totalTime", 0) // 60

        first_leg_data = legs[0]
        last_leg_data = legs[-1]

        departure_at_str = first_leg_data.get("departureTime")
        arrival_at_str = last_leg_data.get("arrivalTime")
        carrier_data = first_leg_data.get("carriersData", [{}])[0]
        flight_info = first_leg_data.get("flightInfo", {})
        flight_number = flight_info.get("flightNumber", "")
        aircraft_type = segment.get("aircraftType", "")

        if not all(
            [
                departure_at_str,
                arrival_at_str,
                departure_airport_info,
                arrival_airport_info,
                carrier_data,
            ]
        ):
            return None

        departure_time = datetime.fromisoformat(departure_at_str).strftime("%I:%M %p")
        arrival_time = datetime.fromisoformat(arrival_at_str).strftime("%I:%M %p")
        departure_airport = f"{departure_airport_info.get('name')} ({departure_airport_info.get('code')})"
        arrival_airport = f"{arrival_airport_info.get('name')} ({arrival_airport_info.get('code')})"
        airline = carrier_data.get("name", "Unknown Airline")

        is_layover = len(legs) > 1
        layover_airport = None
        layover_duration_minutes = None

        if is_layover:
            layover_airport_info = first_leg_data.get("arrivalAirport")
            layover_airport = f"{layover_airport_info.get('name')} ({layover_airport_info.get('code')})"
            first_leg_arrival = datetime.fromisoformat(first_leg_data.get("arrivalTime"))
            second_leg_departure = datetime.fromisoformat(legs[1].get("departureTime"))
            layover_duration_minutes = int(
                (second_leg_departure - first_leg_arrival).total_seconds() / 60
            )

        return FlightLeg(
            departure_time=departure_time,
            arrival_time=arrival_time,
            departure_airport=departure_airport,
            arrival_airport=arrival_airport,
            duration_minutes=total_duration_minutes,
            airline=airline,
            flight_number=f"{carrier_data.get('code', '')}{flight_number}",
            aircraft_type=aircraft_type,
            is_layover=is_layover,
            layover_airport=layover_airport,
            layover_duration_minutes=layover_duration_minutes,
        )
    except Exception:
        return None




"""
fetch_flight_data là một lần gọi HTTP tới Booking.com: tìm vé khứ hồi cho một cặp sân bay (ví dụ CDG → JFK).
 Nó không parse, không rank; chỉ lấy JSON thô hoặc None nếu lỗi.
"""
def fetch_flight_data(origin, dest, start_date, end_date, person, headers):
    url = "https://booking-com18.p.rapidapi.com/flights/v2/search-roundtrip"
    # 1 số tham số khi truyền lúc gọi API get 
    querystring = {
        "departId": origin, # mã sân bay đi
        "arrivalId": dest, # mã sân bay đến
        "departDate": start_date, # ngày đi 
        "returnDate": end_date, # ngày về
        "adults": str(person), # số người
        "sort": "CHEAPEST", # sắp xếp theo giá rẻ nhất
        "currency_code": "EUR", # đơn vị tiền tệ
    }
    print(f"🚀 Parallel Request: {origin} -> {dest}") # log ra màn hình để debug
    try:
        response = requests.get(url, headers=headers, params=querystring, timeout=20)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"API Error for {origin}->{dest}: {e}")
        return None


def fetch_oneway_data(origin, dest, start_date, person, headers):
    url = "https://booking-com18.p.rapidapi.com/flights/v2/search-oneway"
    querystring = {
        "departId": origin,
        "arrivalId": dest,
        "departDate": start_date,
        "adults": str(person),
        "sort": "CHEAPEST",
        "currency_code": "EUR",
    }
    print(f"🚀 One-way request: {origin} -> {dest} on {start_date}")
    try:
        response = requests.get(url, headers=headers, params=querystring, timeout=20)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"API Error for one-way {origin}->{dest}: {e}")
        return None


def _offers_from_payload(data: dict) -> list:
    if not data:
        return []
    payload = data.get("data") or {}
    return payload.get("flightOffers") or payload.get("flights") or []


def _price_from_offer(offer: dict) -> float:
    price_info = (offer.get("priceBreakdown") or {}).get("total") or {}
    return (price_info.get("units", 0) or 0) + (price_info.get("nanos", 0) or 0) / 1e9


def _rapid_headers() -> dict:
    return {
        "x-rapidapi-key": (os.getenv("RAPIDAPI_KEY") or "").strip(),
        "x-rapidapi-host": "booking-com18.p.rapidapi.com",
    }


def _split_iata(value: str) -> List[str]:
    return [part.strip().upper() for part in (value or "").split(",") if part.strip()]



"""
Hàm nhận danh sách mã sân bay đi, danh sách mã sân bay đến, ngày đi/về, số người.
 Nó gọi Booking.com song song cho từng cặp, parse JSON thành FlightInfo,
 rồi trả về tối đa 10 chuyến tốt nhất theo công thức “rẻ + không bay quá lâu”.
 ---------------------------------------------
 origin_codes × dest_codes
        ↓
  gọi API song song (tối đa 5 request cùng lúc)
        ↓
  parse từng offer → FlightInfo
        ↓
  sort theo giá + 0.5 × tổng phút bay
        ↓
  lấy 10 chuyến đầu
"""
def search_roundtrip_airports(
    origin_codes: List[str],
    dest_codes: List[str],
    start_date: str,
    end_date: str,
    person: int,
) -> List[FlightInfo]:
    if not origin_codes or not dest_codes:
        return []

    all_flight_options: List[FlightInfo] = []
    headers = _rapid_headers()

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        tasks = [
            executor.submit(
                fetch_flight_data, origin, dest, start_date, end_date, person, headers
            )
            for origin in origin_codes
            for dest in dest_codes
        ]
        for future in concurrent.futures.as_completed(tasks):
            data = future.result()
            if not data:
                continue
            for offer in _offers_from_payload(data):
                segments = offer.get("segments")
                if not segments or len(segments) < 2:
                    continue
                departure_leg = parse_journey_segment(segments[0])
                return_leg = parse_journey_segment(segments[1])
                if not departure_leg or not return_leg:
                    continue
                total_duration = departure_leg.duration_minutes + return_leg.duration_minutes
                all_flight_options.append(
                    FlightInfo(
                        price=_price_from_offer(offer),
                        departure_leg=departure_leg,
                        return_leg=return_leg,
                        total_duration_minutes=total_duration,
                    )
                )

    if not all_flight_options:
        return []

    all_flight_options.sort(key=lambda item: item.price + (item.total_duration_minutes * 0.5))
    print(f"Found {len(all_flight_options)} flights. Returning top 10.")
    return all_flight_options[:10]


def search_oneway_airports(
    origin_codes: List[str],
    dest_codes: List[str],
    start_date: str,
    person: int,
) -> List[FlightInfo]:
    if not origin_codes or not dest_codes:
        return []

    all_flight_options: List[FlightInfo] = []
    headers = _rapid_headers()

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        tasks = [
            executor.submit(fetch_oneway_data, origin, dest, start_date, person, headers)
            for origin in origin_codes
            for dest in dest_codes
        ]
        for future in concurrent.futures.as_completed(tasks):
            data = future.result()
            if not data:
                continue
            for offer in _offers_from_payload(data):
                segments = offer.get("segments") or []
                if not segments:
                    continue
                departure_leg = parse_journey_segment(segments[0])
                if not departure_leg:
                    continue
                all_flight_options.append(
                    FlightInfo(
                        price=_price_from_offer(offer),
                        departure_leg=departure_leg,
                        return_leg=None,
                        total_duration_minutes=departure_leg.duration_minutes,
                    )
                )

    if not all_flight_options:
        return []

    all_flight_options.sort(key=lambda item: item.price + (item.total_duration_minutes * 0.5))
    print(f"Found {len(all_flight_options)} one-way flights. Returning top 10.")
    return all_flight_options[:10]


def _is_one_way(start_date: str, end_date: str) -> bool:
    return not end_date or start_date == end_date

## Tìm vé khứ hồi 
def search_roundtrip(
    origin_iata: str,
    dest_iata: str,
    start_date: str,
    end_date: str,
    person: int,
) -> List[FlightInfo]:
    origins = _split_iata(origin_iata)
    dests = _split_iata(dest_iata)
    if _is_one_way(start_date, end_date):
        return search_oneway_airports(origins, dests, start_date, person)
    return search_roundtrip_airports(
        origins,
        dests,
        start_date,
        end_date,
        person,
    )
