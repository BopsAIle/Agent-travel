import sys
from pathlib import Path
from typing import List

_SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVER_ROOT))

from fastapi import FastAPI
from langchain_core.tools import StructuredTool
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field

from packages.agent_runtime import (
    AgentRunRequest,
    AgentRunResponse,
    DomainMemory,
    agent_service_lifespan,
    run_agent,
    session_scope,
    skills_payload,
)
from schemas import FlightInfo
from search import find_iata_codes, search_roundtrip, search_roundtrip_airports, search_oneway_airports

SKILLS_DIR = Path(__file__).resolve().parent / "skills"

app = FastAPI(lifespan=agent_service_lifespan)
Instrumentator().instrument(app).expose(app)


class FlightSearchRequest(BaseModel):
    origin: str
    destination: str
    start_date: str
    end_date: str
    person: int


class LookupIataArgs(BaseModel):
    city: str = Field(description="City name to resolve to IATA airport codes.")


class SearchRoundtripArgs(BaseModel):
    origin_iata: str = Field(
        description="Origin IATA code, or comma-separated codes from lookup_iata."
    )
    dest_iata: str = Field(
        description="Destination IATA code, or comma-separated codes from lookup_iata."
    )
    start_date: str = Field(description="Depart date YYYY-MM-DD.")
    end_date: str = Field(description="Return date YYYY-MM-DD.")
    person: int = Field(description="Number of adults.")


def _dump_flights(flights: List[FlightInfo]) -> List[dict]:
    return [item.model_dump() for item in flights]
    

def _flight_tools(memory: DomainMemory) -> List[StructuredTool]:
    def lookup_iata(city: str) -> List[str]:
        cached = memory.get_cache(city)
        if cached is not None:
            print(f"-> IATA cache hit for {city}: {cached}")
            return cached
        codes = find_iata_codes(city)
        memory.set_cache(city, codes)
        print(f"-> IATA cache miss for {city}, stored {codes}")
        return codes

    def search_roundtrip_tool(
        origin_iata: str,
        dest_iata: str,
        start_date: str,
        end_date: str,
        person: int,
    ) -> List[dict]:
        flights = search_roundtrip(origin_iata, dest_iata, start_date, end_date, person)
        return _dump_flights(flights)

    return [
        StructuredTool.from_function(
            func=lookup_iata,
            name="lookup_iata",
            description="Resolve a city name to IATA airport codes. Uses domain cache when possible.",
            args_schema=LookupIataArgs,
        ),
        StructuredTool.from_function(
            func=search_roundtrip_tool,
            name="search_roundtrip",
            description="Search Booking.com offers for IATA codes. One-way if start_date equals end_date. Do not invent prices.",
            args_schema=SearchRoundtripArgs,
        ),
    ]


@app.get("/agent/skills")
def agent_skills():
    return skills_payload(SKILLS_DIR)


@app.post("/agent/run", response_model=AgentRunResponse)
def agent_run(body: AgentRunRequest):
    print(f"-> flight /agent/run task={body.task} skills={SKILLS_DIR}")
    with session_scope() as db:
        memory = DomainMemory(db, "flight")
        return run_agent(
            agent_id="flight",
            skills_dir=SKILLS_DIR,
            tools=_flight_tools(memory),
            request=body,
            db=db,
        )


@app.post("/search", response_model=List[FlightInfo])
def search_flights(request: FlightSearchRequest):
    print(f"Processing flight search request: {request.origin} -> {request.destination}")
    origin_iata_list = find_iata_codes(request.origin)
    destination_iata_list = find_iata_codes(request.destination)
    if not origin_iata_list or not destination_iata_list:
        return []
    if not request.end_date or request.start_date == request.end_date:
        return search_oneway_airports(
            origin_iata_list,
            destination_iata_list,
            request.start_date,
            request.person,
        )
    return search_roundtrip_airports(
        origin_iata_list,
        destination_iata_list,
        request.start_date,
        request.end_date,
        request.person,
    )
