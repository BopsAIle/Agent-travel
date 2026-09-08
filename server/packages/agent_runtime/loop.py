## loop.py : file này chứa hàm run_tool_loop để chạy vòng lặp tool loop



from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool

MAX_TOOL_STEPS = 4


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)


def _tool_map(tools: Sequence[BaseTool]) -> Dict[str, BaseTool]:
    return {tool.name: tool for tool in tools}

## Hàm run_tool_loop để chạy vòng lặp tool loop
def run_tool_loop(
    llm,
    tools: Sequence[BaseTool],
    system_prompt: str,
    user_prompt: str,
    *,
    max_steps: int = MAX_TOOL_STEPS,
    stop_on_tool: Optional[str] = "submit_result",
) -> Tuple[Optional[AIMessage], List[BaseMessage], List[dict]]:
    """Bind tools and run up to max_steps model→tool rounds.

    Returns (last AI message, full transcript, executed tool calls).
    """
    bound = llm.bind_tools(list(tools))
    messages: List[BaseMessage] = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]
    executed: List[dict] = []
    last_ai: Optional[AIMessage] = None
    lookup = _tool_map(tools)

    for step in range(max_steps):
        ai = bound.invoke(messages)
        last_ai = ai
        messages.append(ai)
        tool_calls = getattr(ai, "tool_calls", None) or []
        if not tool_calls:
            print(f"-> Tool loop step {step + 1}: model returned text, stopping.")
            break

        stop = False
        for call in tool_calls:
            name = call.get("name") or ""
            args = call.get("args") or {}
            call_id = call.get("id") or name
            tool = lookup.get(name)
            print(f"-> Tool loop step {step + 1}: {name}({_as_text(args)[:200]})")
            if tool is None:
                output: Any = {"error": f"Unknown tool: {name}"}
            else:
                try:
                    output = tool.invoke(args)
                except Exception as exc:
                    output = {"error": str(exc)}
            executed.append({"name": name, "args": args, "output": output})
            messages.append(
                ToolMessage(content=_as_text(output), tool_call_id=call_id, name=name)
            )
            if stop_on_tool and name == stop_on_tool:
                stop = True
        if stop:
            print(f"-> Tool loop stopped after {stop_on_tool}.")
            break
    else:
        print(f"-> Tool loop reached max_steps={max_steps}.")

    return last_ai, messages, executed
