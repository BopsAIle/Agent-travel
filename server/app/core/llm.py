"""Client LLM dung chung + goi tool theo schema (tu dong vet JSON bi cat cut)."""


import json
import os
from typing import Optional, Type, TypeVar

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.core.config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OPENAI_REASONING_EFFORT,
)
from app.core.telemetry import tracked_invoke
from app.domain.quality import sanitize_and_flag


openai_api_key = OPENAI_API_KEY
openai_model = OPENAI_MODEL
openai_reasoning_effort = OPENAI_REASONING_EFFORT
gemini_api_key = GEMINI_API_KEY

if not all([openai_api_key, gemini_api_key]):
    raise ValueError("OPENAI_API_KEY or GEMINI_API_KEY is missing from .env file!")


def _is_gpt5_family(model: str) -> bool:
    return (model or "").lower().startswith("gpt-5")

def make_chat_openai(*, max_tokens: int, temperature: float = 0) -> ChatOpenAI:
    """Build a ChatOpenAI client compatible with GPT-5.6 tool calling."""
    kwargs = {
        "model": openai_model,
        "api_key": openai_api_key,
        "max_retries": 2,
        "max_tokens": max_tokens,
    }
    if _is_gpt5_family(openai_model):
        # Chat Completions rejects GPT-5.6 function tools unless reasoning_effort is none.
        kwargs["temperature"] = None
        kwargs["use_responses_api"] = True
        kwargs["reasoning_effort"] = openai_reasoning_effort
    else:
        kwargs["temperature"] = temperature
    return ChatOpenAI(**kwargs)

llm = make_chat_openai(max_tokens=4096, temperature=0)

llm_gemini = ChatGoogleGenerativeAI(
    model=GEMINI_MODEL,
    temperature=0.1,
    google_api_key=gemini_api_key
)

SchemaT = TypeVar("SchemaT", bound=BaseModel)

def _failed_generation_from_exception(exc: Exception) -> Optional[str]:
    """Pull a truncated tool-call payload out of a 400 tool_use_failed error."""
    current: Optional[BaseException] = exc
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        body = getattr(current, "body", None)
        if isinstance(body, dict):
            gen = (body.get("error") or {}).get("failed_generation")
            if isinstance(gen, str) and gen.strip():
                return gen
        response = getattr(current, "response", None)
        if response is not None:
            try:
                data = response.json()
                gen = (data.get("error") or {}).get("failed_generation")
                if isinstance(gen, str) and gen.strip():
                    return gen
            except Exception:
                pass
        current = getattr(current, "__cause__", None) or getattr(current, "__context__", None)

    text = str(exc)
    marker = "failed_generation"
    idx = text.find(marker)
    if idx == -1:
        return None
    rest = text[idx + len(marker):]
    brace = rest.find("{")
    if brace == -1:
        return None
    return rest[brace:]

def _close_truncated_json(text: str) -> Optional[dict]:
    """Best-effort parse of truncated / lightly invalid tool JSON."""
    start = text.find("{")
    if start == -1:
        return None
    chunk = text[start:].replace("\\'", "'")

    def try_load(candidate: str) -> Optional[dict]:
        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None

    parsed = try_load(chunk)
    if parsed:
        return parsed

    last = len(chunk)
    while last > 0:
        last = chunk.rfind("}", 0, last)
        if last == -1:
            break
        prefix = chunk[: last + 1].rstrip().rstrip(",")
        missing_square = prefix.count("[") - prefix.count("]")
        missing_curly = prefix.count("{") - prefix.count("}")
        if missing_square < 0 or missing_curly < 0:
            continue
        repaired = prefix + ("]" * missing_square) + ("}" * missing_curly)
        parsed = try_load(repaired)
        if parsed:
            return parsed
    return None

def _schema_from_parsed(schema: Type[SchemaT], parsed: dict) -> SchemaT:
    args = parsed.get("arguments", parsed)
    if isinstance(args, str):
        args = _close_truncated_json(args) or {}
    if not isinstance(args, dict):
        raise ValueError("Tool arguments were not an object")
    fields = set(schema.model_fields)
    return schema(**{k: v for k, v in args.items() if k in fields})

def _scrub_schema_result(result: SchemaT) -> SchemaT:
    """Drop looping prose sometimes salvaged from a failed tool call."""
    reply = getattr(result, "reply", None)
    if not isinstance(reply, str):
        return result
    cleaned, bad = sanitize_and_flag(reply)
    if not bad and cleaned == reply:
        return result
    try:
        result.reply = "" if bad else cleaned
    except Exception:
        return result
    if bad:
        print("-> Dropped degenerate reply from tool payload.")
    return result

def invoke_tool_schema(model, schema: Type[SchemaT], prompt: str, retries: int = 3) -> SchemaT:
    """Call LLM tools, and salvage JSON when a truncated tool call is rejected."""
    bound = model.bind_tools([schema], tool_choice=schema.__name__)
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        try:
            message = tracked_invoke(bound, prompt)
            if message.tool_calls:
                return _scrub_schema_result(schema(**message.tool_calls[0]["args"]))
            print(f"-> Attempt {attempt + 1}: LLM did not call {schema.__name__}. Retrying...")
        except Exception as e:
            last_error = e
            print(f"-> Attempt {attempt + 1} Error: {e}")
            gen = _failed_generation_from_exception(e)
            if gen:
                parsed = _close_truncated_json(gen)
                if parsed:
                    try:
                        result = _scrub_schema_result(_schema_from_parsed(schema, parsed))
                        print(f"-> Recovered truncated {schema.__name__} JSON from LLM error.")
                        return result
                    except Exception as parse_error:
                        print(f"-> Recovered JSON failed schema validation: {parse_error}")
    if last_error:
        raise last_error
    raise ValueError(f"LLM did not return a valid {schema.__name__}")
