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
from schemas import EventInfo, EventSearchRequest
from search import fetch_events

SKILLS_DIR = Path(__file__).resolve().parent / "skills"

app = FastAPI(lifespan=agent_service_lifespan)
Instrumentator().instrument(app).expose(app)


class SearchEventsArgs(BaseModel):
    city: str = Field(description="City to search for events.")
    start_date: str = Field(description="Start date YYYY-MM-DD.")
    end_date: str = Field(description="End date YYYY-MM-DD.")


def _event_tools() -> List[StructuredTool]:
    def search_events(city: str, start_date: str, end_date: str) -> List[dict]:
        events = fetch_events(city, start_date, end_date)
        return [item.model_dump() for item in events]

    return [
        StructuredTool.from_function(
            func=search_events,
            name="search_events",
            description="Search Ticketmaster events for a city and date range. Do not invent events.",
            args_schema=SearchEventsArgs,
        )
    ]


@app.get("/agent/skills")
def agent_skills():
    return skills_payload(SKILLS_DIR)


@app.post("/agent/run", response_model=AgentRunResponse)
def agent_run(body: AgentRunRequest):
    print(f"-> event /agent/run task={body.task} skills={SKILLS_DIR}")
    with session_scope() as db:
        return run_agent(
            agent_id="event",
            skills_dir=SKILLS_DIR,
            tools=_event_tools(),
            request=body,
            db=db,
        )


@app.post("/search_events", response_model=List[EventInfo])
def search_events(request: EventSearchRequest):
    return fetch_events(request.city, request.start_date, request.end_date)
