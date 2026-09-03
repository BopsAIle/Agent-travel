import os
import requests
import concurrent.futures
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from datetime import datetime
from pydantic import BaseModel
from schemas import FlightInfo, FlightLeg
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI()

Instrumentator().instrument(app).expose(app)

class FlightSearchRequest(BaseModel):
    origin: str
    destination: str
    start_date: str
    end_date: str
    person: int


def find_iata_codes(city_name: str) -> List[str]:
  
    print(f"--- Calling Booking.com auto-complete API for {city_name} ---")
    url = "https://booking-com18.p.rapidapi.com/flights/v2/auto-complete"
    querystring = {"query": city_name}
    headers = {
        "x-rapidapi-key": os.getenv("RAPIDAPI_KEY"),
        "x-rapidapi-host": "booking-com18.p.rapidapi.com"
    }
    try:
        response = requests.get(url, headers=headers, params=querystring)
        response.raise_for_status()
        data = response.json()
        iata_codes = []
        if data.get('data'):
            for location in data['data']:
                if location.get('type') == 'AIRPORT':
                    iata_codes.append(location['code'])
        return iata_codes
    except Exception as e:
        print(f"Error finding IATA for {city_name}: {e}")
        return []

def parse_journey_segment(segment: dict) -> Optional[FlightLeg]:
    try:
        legs = segment.get('legs', [])
        if not legs: return None
        
        departure_airport_info = segment.get('departureAirport')
        arrival_airport_info = segment.get('arrivalAirport')
        total_duration_minutes = segment.get('totalTime', 0) // 60
        
        first_leg_data = legs[0]
        last_leg_data = legs[-1]

        departure_at_str = first_leg_data.get('departureTime')
        arrival_at_str = last_leg_data.get('arrivalTime')
        carrier_data = first_leg_data.get('carriersData', [{}])[0]
        flight_info = first_leg_data.get('flightInfo', {})
        flight_number = flight_info.get('flightNumber', '')
        aircraft_type = segment.get('aircraftType', '') 

        if not all([departure_at_str, arrival_at_str, departure_airport_info, arrival_airport_info, carrier_data]):
            return None

        departure_time = datetime.fromisoformat(departure_at_str).strftime('%I:%M %p')
        arrival_time = datetime.fromisoformat(arrival_at_str).strftime('%I:%M %p')
        departure_airport = f"{departure_airport_info.get('name')} ({departure_airport_info.get('code')})"
        arrival_airport = f"{arrival_airport_info.get('name')} ({arrival_airport_info.get('code')})"
        airline = carrier_data.get('name', 'Unknown Airline')

        is_layover = len(legs) > 1
        layover_airport = None
        layover_duration_minutes = None

        if is_layover:
            layover_airport_info = first_leg_data.get('arrivalAirport')
            layover_airport = f"{layover_airport_info.get('name')} ({layover_airport_info.get('code')})"
            first_leg_arrival = datetime.fromisoformat(first_leg_data.get('arrivalTime'))
            second_leg_departure = datetime.fromisoformat(legs[1].get('departureTime'))
            layover_duration_minutes = int((second_leg_departure - first_leg_arrival).total_seconds() / 60)

        return FlightLeg(
            departure_time=departure_time, arrival_time=arrival_time,
            departure_airport=departure_airport, arrival_airport=arrival_airport,
            duration_minutes=total_duration_minutes,
            airline=airline,
            flight_number=f"{carrier_data.get('code', '')}{flight_number}",
            aircraft_type=aircraft_type,
            is_layover=is_layover,
            layover_airport=layover_airport,
            layover_duration_minutes=layover_duration_minutes
        )
    except Exception as e:
        return None

def fetch_flight_data(origin, dest, start_date, end_date, person, headers):
    url = "https://booking-com18.p.rapidapi.com/flights/v2/search-roundtrip"
    querystring = {
        "departId": origin, "arrivalId": dest, 
        "departDate": start_date, "returnDate": end_date, 
        "adults": str(person), "sort": "CHEAPEST", "currency_code": "EUR"
    }
    print(f"🚀 Parallel Request: {origin} -> {dest}")
    try:
        response = requests.get(url, headers=headers, params=querystring, timeout=20)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"API Error for {origin}->{dest}: {e}")
        return None


@app.post("/search", response_model=List[FlightInfo])
def search_flights(request: FlightSearchRequest):
    print(f"Processing flight search request: {request.origin} -> {request.destination}")
    
    origin_iata_list = find_iata_codes(request.origin)
    destination_iata_list = find_iata_codes(request.destination)
    
    if not origin_iata_list or not destination_iata_list:
        return []

    all_flight_options = []
    rapid_key = os.getenv("RAPIDAPI_KEY")
    headers = { "x-rapidapi-key": rapid_key, "x-rapidapi-host": "booking-com18.p.rapidapi.com" }


    tasks = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        for origin in origin_iata_list:
            for dest in destination_iata_list:
                tasks.append(
                    executor.submit(fetch_flight_data, origin, dest, request.start_date, request.end_date, request.person, headers)
                )
        
        for future in concurrent.futures.as_completed(tasks):
            data = future.result()
            if not data: continue
            
            offers = data.get('data', {}).get('flightOffers', []) or data.get('data', {}).get('flights', [])
            for offer in offers:
                price_info = offer.get('priceBreakdown', {}).get('total', {})
                total_price = price_info.get('units', 0) + price_info.get('nanos', 0) / 1e9
                segments = offer.get('segments')
                if not segments or len(segments) < 2: continue

                departure_leg = parse_journey_segment(segments[0])
                return_leg = parse_journey_segment(segments[1])
                
                if not departure_leg or not return_leg: continue
                
                total_duration = departure_leg.duration_minutes + return_leg.duration_minutes
                all_flight_options.append(FlightInfo(
                    price=total_price, departure_leg=departure_leg,
                    return_leg=return_leg, total_duration_minutes=total_duration
                ))

    if not all_flight_options:
        return []

    all_flight_options.sort(key=lambda x: x.price + (x.total_duration_minutes * 0.5))
    
    print(f"Found {len(all_flight_options)} flights. Returning top 10.")
    return all_flight_options[:10]