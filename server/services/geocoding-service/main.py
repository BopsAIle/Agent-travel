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
from geocode import extract_queries, nominatim_geocode
from schemas import GeocodeRequest, GeocodeResponse

SKILLS_DIR = Path(__file__).resolve().parent / "skills"

app = FastAPI(lifespan=agent_service_lifespan)
Instrumentator().instrument(app).expose(app)


class LookupCoordsArgs(BaseModel):
    query: str = Field(description="Place name, ideally with city, e.g. 'Eiffel Tower, Paris'.")


def lookup_coords(query: str, memory: DomainMemory) -> dict:
    cached = memory.get_cache(query)
    if cached is not None:
        print(f"-> geocode cache hit for {query}")
        if isinstance(cached, dict):
            cached = {**cached, "query": query}
        return cached
    result = nominatim_geocode(query)
    if result.get("latitude") is not None:
        memory.set_cache(query, result)
        print(f"-> geocode cache miss for {query}, stored coordinates")
    return result


def _geo_tools(memory: DomainMemory) -> List[StructuredTool]:
    def lookup_coords_tool(query: str) -> dict:
        return lookup_coords(query, memory)

    return [
        StructuredTool.from_function(
            func=lookup_coords_tool,
            name="lookup_coords",
            description="Resolve a place query to lat/lon. Checks cache first, then Nominatim.",
            args_schema=LookupCoordsArgs,
        )
    ]


@app.get("/agent/skills")
def agent_skills():
    return skills_payload(SKILLS_DIR)


@app.post("/agent/run", response_model=AgentRunResponse)
def agent_run(body: AgentRunRequest):
    print(f"-> geocoding /agent/run task={body.task} skills={SKILLS_DIR}")
    queries = extract_queries(body)
    with session_scope() as db:
        memory = DomainMemory(db, "geocoding")
        resolved = []
        unresolved = []
        for query in queries:
            result = lookup_coords(query, memory)
            if result.get("latitude") is not None and result.get("longitude") is not None:
                resolved.append(result)
            else:
                unresolved.append(query)

        if queries and not unresolved:
            selected = resolved[0] if resolved else None
            return AgentRunResponse(
                options=resolved,
                selected=selected,
                reasoning="Resolved from cache and Nominatim without an LLM call.",
                memory_hits=list(memory.hits),
            )

        request = body
        if unresolved:
            extra = "Ambiguous or missing queries: " + "; ".join(unresolved)
            request = body.model_copy(
                update={"feedback": (body.feedback + "\n" + extra).strip()}
            )
        return run_agent(
            agent_id="geocoding",
            skills_dir=SKILLS_DIR,
            tools=_geo_tools(memory),
            request=request,
            db=db,
        )


@app.post("/geocode", response_model=GeocodeResponse)
def geocode_location(request: GeocodeRequest):
    result = nominatim_geocode(request.query)
    return GeocodeResponse(
        latitude=result.get("latitude"),
        longitude=result.get("longitude"),
        address=result.get("address"),
    )
