import os
import sys
from pathlib import Path

_SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVER_ROOT))

from typing import List

from fastapi import FastAPI, HTTPException
from langchain_tavily import TavilySearch
from packages.agent_runtime import agent_service_lifespan
from schemas import ActivitySearchRequest, PlaceDetailRequest, PlaceDetailResponse, PlaceSnippet
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(lifespan=agent_service_lifespan)

Instrumentator().instrument(app).expose(app)

@app.post("/search_activities", response_model=str)
def search_activities(request: ActivitySearchRequest):
    print(f"--- Processing Activity Search for {request.destination} ---")
    
    tavily_api_key = os.getenv("TAVILY_API_KEY")
    if not tavily_api_key:
        raise HTTPException(status_code=500, detail="TAVILY_API_KEY not found in environment")

    all_results_summary = ""
    tavily_search = TavilySearch(max_results=4, api_key=tavily_api_key)
    
    for interest in request.interests:
        query = f"specific and famous '{interest}' places, landmarks, or experiences in {request.destination}. Give me names of places, not tours."
        print(f"-> Searching Tavily for: {interest}")
        
        try:
            response_data = tavily_search.invoke(query)
            
            search_results = []
            if isinstance(response_data, dict):
                search_results = response_data.get('results', [])
            elif isinstance(response_data, list):
                search_results = response_data
            
            all_results_summary += f"\n--- Search Results for '{interest}' in {request.destination} ---\n"

            if not search_results:
                all_results_summary += "No specific results found for this interest.\n\n"
                continue

            for result in search_results:
                if isinstance(result, dict):
                    title = result.get('title', 'N/A')
                    content = result.get('content', 'No content')
                    all_results_summary += f"Title: {title}\nContent: {content}\n\n"
        
        except Exception as e:
            print(f"Tavily Error for '{interest}': {e}")
            continue

    if not all_results_summary.strip():
        return "No relevant activities found from web search."
         
    return all_results_summary


@app.post("/place_details", response_model=PlaceDetailResponse)
def place_details(request: PlaceDetailRequest):
    """Look up visitor facts for one named place."""
    tavily_api_key = os.getenv("TAVILY_API_KEY")
    if not tavily_api_key:
        raise HTTPException(status_code=500, detail="TAVILY_API_KEY not found in environment")

    place = (request.place_name or "").strip()
    destination = (request.destination or "").strip()
    if not place:
        raise HTTPException(status_code=400, detail="place_name is required")

    where = f"{place} {destination}".strip()
    query = (
        f"{where} visitor guide address opening hours tickets how to get there "
        "what to see nearby"
    )
    print(f"-> Place detail search: {query}")
    tavily_search = TavilySearch(max_results=5, api_key=tavily_api_key)
    snippets: List[PlaceSnippet] = []
    try:
        response_data = tavily_search.invoke(query)
        raw_results = []
        if isinstance(response_data, dict):
            raw_results = response_data.get("results", []) or []
        elif isinstance(response_data, list):
            raw_results = response_data
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            content = (item.get("content") or "").strip()
            if not content:
                continue
            snippets.append(
                PlaceSnippet(
                    title=item.get("title") or "N/A",
                    url=item.get("url") or "",
                    content=content[:1200],
                )
            )
    except Exception as exc:
        print(f"Tavily place-detail error: {exc}")

    return PlaceDetailResponse(
        place_name=place,
        destination=destination,
        results=snippets,
    )