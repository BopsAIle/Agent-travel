## Khai báo client kết nối API OpenAI

from __future__ import annotations

import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()


def _is_gpt5_family(model: str) -> bool:
    return (model or "").lower().startswith("gpt-5")

## Tạo ra client kết nối API
def make_agent_llm(*, max_tokens: int = 4096, temperature: float = 0) -> ChatOpenAI:
    """Chat model for the in-service tool loop.

    Prefers Groq when GROQ_API_KEY is set (plan default). Otherwise uses the
    same OpenAI env as the orchestrator so local .env works without extra keys.
    """
    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key:
        return ChatOpenAI(
            model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            api_key=groq_key,
            base_url="https://api.groq.com/openai/v1",
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=2,
        )

    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        raise ValueError("GROQ_API_KEY or OPENAI_API_KEY is required for agent_runtime")

    model = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
    kwargs = {
        "model": model,
        "api_key": openai_key,
        "max_retries": 2,
        "max_tokens": max_tokens,
    }
    if _is_gpt5_family(model):
        kwargs["temperature"] = None
        kwargs["use_responses_api"] = True
        kwargs["reasoning_effort"] = os.getenv("OPENAI_REASONING_EFFORT", "low")
    else:
        kwargs["temperature"] = temperature
    return ChatOpenAI(**kwargs)
