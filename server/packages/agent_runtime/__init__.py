"""Shared skill, domain memory, and tool-loop runtime for agent microservices.

Import as ``packages.agent_runtime`` when the server root is on PYTHONPATH.
Heavy modules (DB, LLM) load on first use so skill/contract stay importable
without Postgres or LangChain.
"""

from .contract import AgentRunRequest, AgentRunResponse, TripPayload
from .skills import Skill, load_skills, load_system_prompt, skills_payload

__all__ = [
    "AgentCache",
    "AgentFact",
    "AgentRunRequest",
    "AgentRunResponse",
    "AgentRuntimeBase",
    "AgentWorking",
    "DomainMemory",
    "MAX_TOOL_STEPS",
    "Skill",
    "TripPayload",
    "init_agent_db",
    "load_skills",
    "load_system_prompt",
    "make_agent_llm",
    "run_agent",
    "run_tool_loop",
    "session_scope",
    "skills_payload",
]

_LAZY = {
    "AgentCache": (".models", "AgentCache"),
    "AgentFact": (".models", "AgentFact"),
    "AgentRuntimeBase": (".models", "AgentRuntimeBase"),
    "AgentWorking": (".models", "AgentWorking"),
    "DomainMemory": (".memory", "DomainMemory"),
    "MAX_TOOL_STEPS": (".loop", "MAX_TOOL_STEPS"),
    "init_agent_db": (".db", "init_agent_db"),
    "make_agent_llm": (".llm", "make_agent_llm"),
    "run_agent": (".runner", "run_agent"),
    "run_tool_loop": (".loop", "run_tool_loop"),
    "session_scope": (".db", "session_scope"),
}


def __getattr__(name: str):
    target = _LAZY.get(name)
    if not target:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = target
    from importlib import import_module

    value = getattr(import_module(module_name, __name__), attr)
    globals()[name] = value
    return value
