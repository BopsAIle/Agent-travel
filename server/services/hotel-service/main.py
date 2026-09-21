import base64
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

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
    # Tuoi tre em da biet (>= 2). Rong = chua biet tuoi, tinh nhu nguoi lon.
    child_ages: Optional[List[int]] = None


class LookupLocationArgs(BaseModel):
    city: str = Field(description="Destination city to resolve to a Booking.com location token.")


class SearchHotelsArgs(BaseModel):
    location_id: str = Field(
        description=(
            "The EXACT opaque location token returned by lookup_location_id in this run. "
            "Copy it verbatim. It is not a number, and not dest_id."
        )
    )
    start_date: str = Field(description="Check-in date YYYY-MM-DD.")
    end_date: str = Field(description="Check-out date YYYY-MM-DD.")
    person: int = Field(description="Total number of travellers, children included.")


def dest_id_of(token: str) -> str:
    """Doc `dest_id` nam trong envelope base64 ma Booking.com tra ve.

    `/stays/auto-complete` tra moi dong hai field cung trong nhu "ma dia diem":
    `id` (envelope JSON base64 — gia tri `/stays/search` CHAP NHAN) va `dest_id`
    (so nhu "-716583" — trong giong ma hon nhung `/stays/search` tra 400
    "Location is not available").

    Ham nay chi de nhan dien khi model lo truyen `dest_id`; gia tri gui len API
    luon la token base64. Dung doi `find_location_id` sang tra `dest_id`.
    """
    try:
        decoded = base64.b64decode(str(token) + "==").decode("utf-8")
        return str(json.loads(decoded).get("dest_id") or "")
    except Exception:
        return ""


def _adults_for(person, children_ages) -> int:
    """So nguoi lon gui len API: tru tre em da biet tuoi khoi tong so khach."""
    total = max(1, int(person or 1))
    return max(1, total - len(children_ages or []))


def _hotel_tools(
    memory: DomainMemory,
    children_ages: Optional[List[int]] = None,
) -> List[StructuredTool]:
    resolved_ids = set()
    tokens_by_dest_id: Dict[str, str] = {}

    def _register(location_id: str) -> str:
        resolved_ids.add(location_id)
        dest_id = dest_id_of(location_id)
        if dest_id:
            tokens_by_dest_id[dest_id] = location_id
        return location_id

    def lookup_location_id(city: str) -> Optional[str]:
        cache_key = f"booking18:location:{city.strip().casefold()}"
        cached = memory.get_cache(cache_key)
        if cached is not None:
            print(f"-> location id cache hit for {city}: {cached}")
            return _register(str(cached))
        location_id = find_location_id(city)
        if location_id:
            memory.set_cache(cache_key, location_id)
            print(f"-> location id cache miss for {city}, stored {location_id}")
            return _register(location_id)
        return None

    def search_hotels(
        location_id: str,
        start_date: str,
        end_date: str,
        person: int,
    ) -> List[dict]:
        token = str(location_id or "").strip()
        if token not in resolved_ids:
            # Model co the da tu giai envelope base64 roi dung `dest_id` ben trong.
            # Do la gia tri API tu choi, nen dich ve token that thay vi chan cung.
            token = tokens_by_dest_id.get(token, "")
        if token not in resolved_ids:
            raise HotelProviderError(
                "location_id_not_from_lookup",
                "Pass the exact opaque location token returned by lookup_location_id.",
                status_code=400,
            )
        # children_ages lay tu chinh chuyen di, khong de LLM tu chep lai tuoi.
        hotels = search_hotels_at(
            token, start_date, end_date, _adults_for(person, children_ages), children_ages
        )
        return [item.model_dump() for item in hotels]

    return [
        StructuredTool.from_function(
            func=lookup_location_id,
            name="lookup_location_id",
            description=(
                "Resolve a city to a Booking.com location token. Uses domain cache when possible. "
                "The token is opaque: pass it back verbatim to search_hotels."
            ),
            args_schema=LookupLocationArgs,
        ),
        StructuredTool.from_function(
            func=search_hotels,
            name="search_hotels",
            description=(
                "Search hotels for a location token and stay dates. Use the exact token returned "
                "by lookup_location_id. Do not invent prices."
            ),
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
            tools=_hotel_tools(memory, body.trip.child_ages),
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
            location_id,
            request.start_date,
            request.end_date,
            _adults_for(request.person, request.child_ages),
            request.child_ages,
        )
    except HotelProviderError as exc:
        status_code = 503 if exc.code in {"provider_rate_limited", "provider_unavailable"} else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
