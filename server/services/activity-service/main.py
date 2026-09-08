import sys
from pathlib import Path
from typing import List

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
    agent_service_lifespan,
    run_agent,
    session_scope,
    skills_payload,
)
from schemas import (
    ActivitySearchRequest,
    PlaceDetailRequest,
    PlaceDetailResponse,
)
from search import fetch_place_details, search_places

SKILLS_DIR = Path(__file__).resolve().parent / "skills"

app = FastAPI(lifespan=agent_service_lifespan)
Instrumentator().instrument(app).expose(app)


class SearchPlacesArgs(BaseModel):
    destination: str = Field(description="City or region to search.")
    interests: List[str] = Field(description="Traveler interests such as art, food, history.")


class PlaceDetailsArgs(BaseModel):
    place_name: str = Field(description="Official name of one physical place.")
    destination: str = Field(default="", description="City to disambiguate the place.")


def _activity_tools() -> List[StructuredTool]:
    def search_places_tool(destination: str, interests: List[str]) -> str:
        return search_places(destination, interests)

    def place_details_tool(place_name: str, destination: str = "") -> List[dict]:
        snippets = fetch_place_details(place_name, destination)
        return [item.model_dump() for item in snippets]

    return [
        StructuredTool.from_function(
            func=search_places_tool,
            name="search_places",
            description="Web-search famous physical places for a destination and interests.",
            args_schema=SearchPlacesArgs,
        ),
        StructuredTool.from_function(
            func=place_details_tool,
            name="place_details",
            description="Look up visitor facts for one named place.",
            args_schema=PlaceDetailsArgs,
        ),
    ]


@app.get("/agent/skills")
def agent_skills():
    return skills_payload(SKILLS_DIR)


@app.post("/agent/run", response_model=AgentRunResponse)
def agent_run(body: AgentRunRequest):
    print(f"-> activity /agent/run task={body.task} skills={SKILLS_DIR}")
    with session_scope() as db:
        return run_agent(
            agent_id="activity",
            skills_dir=SKILLS_DIR,
            tools=_activity_tools(),
            request=body,
            db=db,
        )


@app.post("/search_activities", response_model=str)
def search_activities(request: ActivitySearchRequest):
    return search_places(request.destination, request.interests)


@app.post("/place_details", response_model=PlaceDetailResponse)
def place_details(request: PlaceDetailRequest):
    place = (request.place_name or "").strip()
    destination = (request.destination or "").strip()
    if not place:
        raise HTTPException(status_code=400, detail="place_name is required")
    snippets = fetch_place_details(place, destination)
    return PlaceDetailResponse(place_name=place, destination=destination, results=snippets)
