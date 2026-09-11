import os
from typing import List

from fastapi import HTTPException
from langchain_tavily import TavilySearch

from schemas import PlaceSnippet

## GỌi API đến Tavily để tìm kiếm các địa điểm liên quan đến các hoạt động user thích
def search_places(destination: str, interests: List[str]) -> str:
    print(f"--- Processing Activity Search for {destination} ---")
    tavily_api_key = os.getenv("TAVILY_API_KEY")
    if not tavily_api_key:
        raise HTTPException(status_code=500, detail="TAVILY_API_KEY not found in environment")

    all_results_summary = ""
    tavily_search = TavilySearch(max_results=4, api_key=tavily_api_key)

    for interest in interests or []:
        query = (
            f"specific and famous '{interest}' places, landmarks, or experiences in "
            f"{destination}. Give me names of places, not tours."
        )
        print(f"-> Searching Tavily for: {interest}")
        try:
            response_data = tavily_search.invoke(query)
            search_results = []
            if isinstance(response_data, dict):
                search_results = response_data.get("results", [])
            elif isinstance(response_data, list):
                search_results = response_data

            all_results_summary += f"\n--- Search Results for '{interest}' in {destination} ---\n"
            if not search_results:
                all_results_summary += "No specific results found for this interest.\n\n"
                continue
            for result in search_results:
                if isinstance(result, dict):
                    title = result.get("title", "N/A")
                    content = result.get("content", "No content")
                    all_results_summary += f"Title: {title}\nContent: {content}\n\n"
        except Exception as e:
            print(f"Tavily Error for '{interest}': {e}")
            continue

    if not all_results_summary.strip():
        return "No relevant activities found from web search."
    return all_results_summary


def fetch_place_details(place_name: str, destination: str = "") -> List[PlaceSnippet]:
    tavily_api_key = os.getenv("TAVILY_API_KEY")
    if not tavily_api_key:
        raise HTTPException(status_code=500, detail="TAVILY_API_KEY not found in environment")

    place = (place_name or "").strip()
    where = f"{place} {destination}".strip()
    query = f"{where} visitor guide address opening hours tickets how to get there what to see nearby"
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
    return snippets
