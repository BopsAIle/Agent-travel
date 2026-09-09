from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Optional, Sequence

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .contract import AgentRunRequest, AgentRunResponse, TripPayload
from .llm import make_agent_llm
from .loop import run_tool_loop
from .memory import DomainMemory, jsonable
from .skills import load_system_prompt


class SubmitResultArgs(BaseModel):
    options: List[Any] = Field(
        description="Candidate results taken from tool output. Do not invent prices."
    )
    selected_index: int = Field(
        description="0-based index of the chosen option in `options`."
    )
    reasoning: str = Field(description="Why this option was chosen.")
    facts_to_remember: List[str] = Field(
        default_factory=list,
        description="Durable domain preferences only. Never trip dates or specific offers.",
    )


class RememberFactArgs(BaseModel):
    text: str = Field(
        description="One durable domain preference, e.g. 'prefers direct flights'."
    )


def _trip_lines(trip: TripPayload) -> str:
    fields = [
        ("origin", trip.origin),
        ("destination", trip.destination),
        ("start_date", trip.start_date),
        ("end_date", trip.end_date),
        ("person", trip.person),
        ("budget", trip.budget),
        ("interests", trip.interests),
    ]
    lines = []
    for key, value in fields:
        if value in (None, "", []):
            continue
        lines.append(f"{key}: {value}")
    return "\n".join(lines) or "(empty)"


def _dump(value: Any, limit: int = 6000) -> str:
    try:
        text = json.dumps(jsonable(value), ensure_ascii=False, default=str)
    except TypeError:
        text = str(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def build_user_prompt(
    request: AgentRunRequest,
    *,
    facts: List[str],
    working: Optional[dict],
) -> str:
    existing = request.existing_options
    if not existing and working and working.get("options"):
        existing = working.get("options")
    return f"""Task: {request.task}

Trip:
{_trip_lines(request.trip)}

Traveler context (from supervisor — honor these preferences):
{request.traveler_context.strip() or "(none)"}

Feedback:
{request.feedback.strip() or "(none)"}

Existing options (if task=refine and this list is non-empty, do not search again):
{_dump(existing) if existing else "(none)"}

Domain facts retrieved for this traveler:
{chr(10).join(f"- {item}" for item in facts) if facts else "(none)"}

Working memory for this session:
{_dump(working) if working else "(none)"}

Use tools as needed. When you have a final answer, call submit_result.
Write facts_to_remember only for durable domain preferences (airline/style), never this trip's dates.
"""


def _pick_selected(options: List[Any], selected_index: Optional[int]) -> Any:
    if not options:
        return None
    if selected_index is None:
        return options[0]
    if 0 <= selected_index < len(options):
        return options[selected_index]
    return options[0]


def run_agent(
    *,
    agent_id: str,
    skills_dir: str | Path,
    tools: Sequence[BaseTool],
    request: AgentRunRequest,
    db: Optional[Session] = None,
    llm=None,
    fallback_prompt: Optional[str] = None,
    max_steps: int = 4,
) -> AgentRunResponse:
    """Load skill + domain memory, run the tool loop, persist working/facts."""
    hits: List[str] = []
    memory = DomainMemory(db, agent_id, hits=hits)
    query_parts = [
        request.trip.origin,
        request.trip.destination,
        request.traveler_context,
        request.feedback,
    ]
    query = " ".join(part for part in query_parts if part) or agent_id
    #Khi kích hoạt agent, ta sẽ truy hồi thông tin liên quan đến user từ bộ nhớ fact
    facts = memory.retrieve_facts(request.user_id, query, limit=5)
    working = memory.get_working(request.session_id)

    submitted: dict = {}

    def _submit(
        options: List[Any],
        selected_index: int,
        reasoning: str,
        facts_to_remember: Optional[List[str]] = None,
    ) -> str:
        submitted["payload"] = {
            "options": list(options or []),
            "selected_index": selected_index,
            "reasoning": reasoning or "",
            "facts_to_remember": list(facts_to_remember or []),
        }
        return "Result recorded."

    def _remember(text: str) -> str:
        if not text or not str(text).strip():
            return "Ignored empty fact."
            #Hàm add_facts này được LLM quyết định gọi để thêm thông tin liên quan đến user vào bộ nhớ fact
        added = memory.add_facts(request.user_id, [str(text).strip()])
        if added:
            return "Saved durable fact."
        return "Fact already known or memory unavailable."

    builtin = [
        StructuredTool.from_function(
            func=_submit,
            name="submit_result",
            description=(
                "Call this once when you have finished. Pass real options from tools, "
                "the chosen index, reasoning, and optional durable facts."
            ),
            args_schema=SubmitResultArgs,
        ),
        StructuredTool.from_function(
            func=_remember,
            name="remember_fact",
            description=(
                "Store one durable domain preference for this traveler. "
                "Never store this trip's dates, prices, or specific offer ids."
            ),
            args_schema=RememberFactArgs,
        ),
    ]
    all_tools = list(tools) + builtin
    system_prompt = load_system_prompt(skills_dir, fallback=fallback_prompt)
    user_prompt = build_user_prompt(request, facts=facts, working=working)
    model = llm or make_agent_llm()

    print(f"-> {agent_id} agent run task={request.task} session={request.session_id}")
    _, _, executed = run_tool_loop(
        model,
        all_tools,
        system_prompt,
        user_prompt,
        max_steps=max_steps,
        stop_on_tool="submit_result",
    )

    payload = submitted.get("payload")
    if payload is None or not payload.get("options"):
        fallback = _fallback_from_tools(executed)
        if payload is None:
            payload = fallback
        elif fallback.get("options"):
            payload["options"] = fallback["options"]
            if payload.get("selected_index") is None:
                payload["selected_index"] = 0

    options = list(payload.get("options") or [])
    selected = _pick_selected(options, payload.get("selected_index"))
    reasoning = payload.get("reasoning") or ""
    extra_facts = payload.get("facts_to_remember") or []
    if extra_facts:
        memory.add_facts(request.user_id, extra_facts)

    memory.set_working(
        request.session_id,
        {"options": options, "selected": selected, "reasoning": reasoning, "task": request.task},
    )
    return AgentRunResponse(
        options=options,
        selected=selected,
        reasoning=reasoning,
        memory_hits=hits,
    )


def _fallback_from_tools(executed: List[dict]) -> dict:
    submitted_args = None
    last_list = None
    for item in executed:
        if item.get("name") == "submit_result":
            submitted_args = item.get("args") or {}
        output = item.get("output")
        if item.get("name") not in ("submit_result", "remember_fact") and isinstance(output, list) and output:
            last_list = output
    if submitted_args and submitted_args.get("options"):
        return {
            "options": list(submitted_args.get("options") or []),
            "selected_index": submitted_args.get("selected_index"),
            "reasoning": submitted_args.get("reasoning") or "",
            "facts_to_remember": list(submitted_args.get("facts_to_remember") or []),
        }
    if last_list:
        return {
            "options": last_list,
            "selected_index": (submitted_args or {}).get("selected_index") or 0,
            "reasoning": (submitted_args or {}).get("reasoning")
            or "Fallback: Booking.com search results.",
            "facts_to_remember": list((submitted_args or {}).get("facts_to_remember") or []),
        }
    return {
        "options": [],
        "selected_index": None,
        "reasoning": "Tool loop finished without submit_result.",
        "facts_to_remember": [],
    }
