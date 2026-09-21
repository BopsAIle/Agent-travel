from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Optional, Sequence

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .contract import AgentRunRequest, AgentRunResponse, TripPayload
from .facts import normalize_facts
from .llm import make_agent_llm
from .loop import run_tool_loop
from .memory import DomainMemory, jsonable
from .skills import load_system_prompt


class SubmitResultArgs(BaseModel):
    options: List[Any] = Field(
        default_factory=list,
        description=(
            "Candidate results. When a search tool already returned results, the runner "
            "keeps that tool output verbatim and ignores this copy — so never retype or "
            "edit opaque fields (photo URLs, ids, signatures). Pass options here only when "
            "no tool returned them (e.g. refining an existing list)."
        ),
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
        ("adults", trip.adults),
        ("children", trip.children),
        ("child_ages", trip.child_ages),
        ("budget", trip.budget),
        ("interests", trip.interests),
        ("hard_constraints", trip.hard_constraints),
        ("soft_preferences", trip.soft_preferences),
        ("priorities_highest_first", trip.priorities),
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


# Tool khong tra ve danh sach option — bo qua khi di tim nguon option that.
NON_OPTION_TOOLS = ("submit_result", "remember_fact")

# Field du de nhan ra cung mot option giua hai ban danh sach.
IDENTITY_KEYS = ("hotel_name", "name", "title", "airline", "venue", "id")


def _options_from_tools(executed: List[dict]) -> List[Any]:
    """Option do TOOL tra ve, khong qua ban sao do model chep lai.

    `submit_result` bat model go lai toan bo option vao tham so tool call, ke ca
    nhung chuoi opaque nhu URL anh Booking.com co chu ky 64 ky tu hex. Ngay
    21/09/2026 chu ky that `84df5b1e...` bi chep thanh `84dfae0c...`: CDN tra 401
    va report hien bieu tuong anh vo. Tool output la ban duy nhat khong bi bien dang.
    """
    trusted: List[Any] = []
    for item in executed:
        if item.get("name") in NON_OPTION_TOOLS:
            continue
        output = item.get("output")
        if isinstance(output, list) and output:
            trusted = output
    return trusted


def _identity(item: Any) -> str:
    """Khoa nhan dang mot option giua hai ban danh sach."""
    if not isinstance(item, dict):
        return ""
    for key in IDENTITY_KEYS:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().casefold()
    leg = item.get("departure_leg")
    if isinstance(leg, dict):
        parts = [leg.get("airline"), leg.get("flight_number"), leg.get("departure_time")]
        text = " ".join(str(part).strip() for part in parts if part)
        if text:
            return text.casefold()
    return ""


def _align(echoed: List[Any], trusted: List[Any]) -> List[Optional[int]]:
    """Voi moi option model chep lai, tim option goc tuong ung (moi ban goc dung 1 lan)."""
    used = set()
    pairs: List[Optional[int]] = []
    for item in echoed:
        target = _identity(item)
        position = None
        if target:
            for index, candidate in enumerate(trusted):
                if index not in used and _identity(candidate) == target:
                    position = index
                    used.add(index)
                    break
        pairs.append(position)
    return pairs


def _canonical_options(
    payload: dict,
    executed: List[dict],
    existing_options: Optional[Sequence[Any]] = None,
) -> tuple:
    """Chon danh sach option + index duoc chon, uu tien du lieu that tu tool.

    Model quyet dinh CHON cai nao, khong quyet dinh NOI DUNG cua option. Co hai kieu
    agent, phai xu ly khac nhau:

    * chep lai nguyen danh sach tool (hotel/flight: chon 1 trong N) → dung ban goc cua
      tool, index anh xa theo ten. Day la duong da lam hong chu ky anh Booking.com.
    * loc/curate danh sach tool (event/activity: giu 3-4 cai tot nhat) → giu dung danh
      sach model chon, chi va noi dung tung option bang ban goc (khong xoa cong loc).
    """
    echoed = list(payload.get("options") or [])
    index = payload.get("selected_index")
    trusted = _options_from_tools(executed)

    if not trusted:
        if echoed:
            # Khong co gi doi chieu (task=refine khong goi lai tool): giu nguyen ban cua model.
            return echoed, index
        # Model chon tu danh sach da co ma khong chep lai.
        return list(existing_options or []), index

    if not echoed:
        # Model chi tra selected_index; noi dung lay nguyen tu tool.
        if isinstance(index, int) and 0 <= index < len(trusted):
            return trusted, index
        return trusted, 0

    pairs = _align(echoed, trusted)
    if len(echoed) == len(trusted) and all(position is not None for position in pairs):
        mapped = 0
        if isinstance(index, int) and 0 <= index < len(pairs):
            mapped = pairs[index] or 0
        return trusted, mapped

    repaired = [
        trusted[position] if position is not None else item
        for item, position in zip(echoed, pairs)
    ]
    return repaired, index


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
    destination = request.trip.destination
    query_parts = [
        request.trip.origin,
        request.trip.destination,
        request.traveler_context,
        request.feedback,
    ]
    query = " ".join(part for part in query_parts if part) or agent_id
    #Khi kích hoạt agent, ta sẽ truy hồi thông tin liên quan đến user từ bộ nhớ fact
    facts = memory.retrieve_facts(
        request.user_id,
        query,
        limit=5,
        destination=destination,
        other_destinations=memory.other_destinations(request.user_id, destination),
    )
    working = memory.get_working(request.session_id)

    submitted: dict = {}

    def _submit(
        options: Optional[List[Any]] = None,
        selected_index: int = 0,
        reasoning: str = "",
        facts_to_remember: Optional[List[str]] = None,
    ) -> str:
        submitted["payload"] = {
            "options": list(options or []),
            "selected_index": selected_index,
            "reasoning": reasoning or "",
            # normalize_facts: neu LLM tra string thay vi list thi list(string) se cat
            # thanh tung ky tu.
            "facts_to_remember": normalize_facts(facts_to_remember),
        }
        return "Result recorded."

    def _remember(text: str) -> str:
        if not text or not str(text).strip():
            return "Ignored empty fact."
            #Hàm add_facts này được LLM quyết định gọi để thêm thông tin liên quan đến user vào bộ nhớ fact
        added = memory.add_facts(
            request.user_id, [str(text).strip()], destination=destination
        )
        if added:
            return "Saved durable fact."
        return "Fact already known or memory unavailable."

    builtin = [
        StructuredTool.from_function(
            func=_submit,
            name="submit_result",
            description=(
                "Call this once when you have finished. If a search tool already returned "
                "the list, pass only selected_index and reasoning: the runner keeps that "
                "tool output verbatim, while retyped opaque fields (URLs, ids, signatures) "
                "come out corrupted. Pass options only for a list you curated or filtered "
                "yourself. Always explain the pick in reasoning."
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

    options, selected_index = _canonical_options(payload, executed, request.existing_options)
    selected = _pick_selected(options, selected_index)
    reasoning = payload.get("reasoning") or ""
    extra_facts = payload.get("facts_to_remember") or []
    if extra_facts:
        added = memory.add_facts(request.user_id, extra_facts, destination=destination)
        if added:
            print(f"-> {agent_id} stored {added} fact(s) for destination={destination!r}")

    memory.set_working(
        request.session_id,
        {"options": options, "selected": selected, "reasoning": reasoning, "task": request.task},
    )
    errors = []
    for item in executed:
        output = item.get("output")
        if isinstance(output, dict) and output.get("error"):
            error = str(output["error"])[:500]
            if error not in errors:
                errors.append(error)

    return AgentRunResponse(
        options=options,
        selected=selected,
        reasoning=reasoning,
        memory_hits=hits,
        errors=errors,
    )


def _fallback_from_tools(executed: List[dict]) -> dict:
    submitted_args = None
    for item in executed:
        if item.get("name") == "submit_result":
            submitted_args = item.get("args") or {}
    # Uu tien danh sach that do tool tra ve: ban sao trong args cua model co the bi
    # chep lem (xem _options_from_tools).
    last_list = _options_from_tools(executed)
    if submitted_args and submitted_args.get("options") and not last_list:
        return {
            "options": list(submitted_args.get("options") or []),
            "selected_index": submitted_args.get("selected_index"),
            "reasoning": submitted_args.get("reasoning") or "",
            # args tho cua tool call KHONG qua validate pydantic cua SubmitResultArgs,
            # nen phai normalize o day — day chinh la duong tao ra fact 1 ky tu.
            "facts_to_remember": normalize_facts(submitted_args.get("facts_to_remember")),
        }
    if last_list:
        return {
            "options": last_list,
            "selected_index": (submitted_args or {}).get("selected_index") or 0,
            "reasoning": (submitted_args or {}).get("reasoning")
            or "Fallback: Booking.com search results.",
            "facts_to_remember": normalize_facts(
                (submitted_args or {}).get("facts_to_remember")
            ),
        }
    return {
        "options": [],
        "selected_index": None,
        "reasoning": "Tool loop finished without submit_result.",
        "facts_to_remember": [],
    }
