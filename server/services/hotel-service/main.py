import sys
from pathlib import Path
from typing import List, Optional

_SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVER_ROOT))

from fastapi import FastAPI, HTTPException
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
from schemas import HotelInfo
from search import HotelProviderError, find_location_id, search_hotels_at

SKILLS_DIR = Path(__file__).resolve().parent / "skills"

app = FastAPI(lifespan=agent_service_lifespan)
Instrumentator().instrument(app).expose(app)


class HotelSearchRequest(BaseModel):
    destination: str
    start_date: str
    end_date: str
    person: int


class LookupLocationArgs(BaseModel):
    city: str = Field(description="Destination city to resolve to a Booking.com location id.")


class SearchHotelsArgs(BaseModel):
    location_id: str = Field(description="Booking.com location id from lookup_location_id.")
    start_date: str = Field(description="Check-in date YYYY-MM-DD.")
    end_date: str = Field(description="Check-out date YYYY-MM-DD.")
    person: int = Field(description="Number of adults.")


def _hotel_tools(memory: DomainMemory) -> List[StructuredTool]:
    resolved_ids = set()

    def lookup_location_id(city: str) -> Optional[str]:
        cache_key = f"booking18:location:{city.strip().casefold()}"
        cached = memory.get_cache(cache_key)
        if cached is not None:
            print(f"-> location id cache hit for {city}: {cached}")
            location_id = str(cached)
            resolved_ids.add(location_id)
            return location_id
        location_id = find_location_id(city)
        if location_id:
            resolved_ids.add(location_id)
            memory.set_cache(cache_key, location_id)
            print(f"-> location id cache miss for {city}, stored {location_id}")
        return location_id

    def search_hotels(
        location_id: str,
        start_date: str,
        end_date: str,
        person: int,
    ) -> List[dict]:
        if location_id not in resolved_ids:
            raise HotelProviderError(
                "provider_bad_request",
                "location_id must come from lookup_location_id in this agent run.",
                status_code=400,
            )
        hotels = search_hotels_at(location_id, start_date, end_date, person)
        return [item.model_dump() for item in hotels]

    return [
        StructuredTool.from_function(
            func=lookup_location_id,
            name="lookup_location_id",
            description="Resolve a city to a Booking.com location id. Uses domain cache when possible.",
            args_schema=LookupLocationArgs,
        ),
        StructuredTool.from_function(
            func=search_hotels,
            name="search_hotels",
            description="Search hotels for a location id and stay dates. Do not invent prices.",
            args_schema=SearchHotelsArgs,
        ),
    ]


@app.get("/agent/skills")
def agent_skills():
    return skills_payload(SKILLS_DIR)


@app.post("/agent/run", response_model=AgentRunResponse)
def agent_run(body: AgentRunRequest):
    print(f"-> hotel /agent/run task={body.task} skills={SKILLS_DIR}")
    with session_scope() as db:
        memory = DomainMemory(db, "hotel")
        return run_agent(
            agent_id="hotel",
            skills_dir=SKILLS_DIR,
            tools=_hotel_tools(memory),
            request=body,
            db=db,
        )


@app.post("/search", response_model=List[HotelInfo])
def search_hotels(request: HotelSearchRequest):
    print(f"Processing hotel search for: {request.destination}")
    try:
        location_id = find_location_id(request.destination)
        if not location_id:
            return []
        return search_hotels_at(
            location_id, request.start_date, request.end_date, request.person
        )
    except HotelProviderError as exc:
        status_code = 503 if exc.code in {"provider_rate_limited", "provider_unavailable"} else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
