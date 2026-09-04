import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

import requests

PRICING = {
    "gpt-5.6-luna": {
        "provider": "openai",
        "input_per_million": 0.20,
        "output_per_million": 1.20,
        "note": "OpenAI listed rate (uncached input / output).",
    },
    "gpt-5.6-terra": {
        "provider": "openai",
        "input_per_million": 2.00,
        "output_per_million": 12.00,
        "note": "OpenAI listed rate (uncached input / output).",
    },
    "gpt-5.6-sol": {
        "provider": "openai",
        "input_per_million": 4.00,
        "output_per_million": 20.00,
        "note": "OpenAI listed rate (uncached input / output).",
    },
    "gpt-4o-mini": {
        "provider": "openai",
        "input_per_million": 0.15,
        "output_per_million": 0.60,
        "note": "OpenAI listed rate (uncached input / output).",
    },
    "gpt-4o": {
        "provider": "openai",
        "input_per_million": 2.50,
        "output_per_million": 10.00,
        "note": "OpenAI listed rate (uncached input / output).",
    },
    "gemini-2.5-flash": {
        "provider": "google",
        "input_per_million": 0.30,
        "output_per_million": 2.50,
        "note": "Gemini Developer API paid tier, output includes thinking tokens.",
    },
    "text-embedding-004": {
        "provider": "google",
        "input_per_million": 0.025,
        "output_per_million": 0.0,
        "note": "Embedding billed on input tokens only.",
    },
}

AGENT_CATALOG = [
    {"id": "conversation", "label": "Conversation", "role": "Chat, slot filling, intent routing"},
    {"id": "memory", "label": "Memory", "role": "Retrieve/write working, semantic, episodic memory"},
    {"id": "planner", "label": "Planner", "role": "Parse the trip request into a structured plan"},
    {"id": "flight_agent", "label": "Flight", "role": "Search flights and pick an option"},
    {"id": "hotel_agent", "label": "Hotel", "role": "Search hotels and pick an option"},
    {"id": "event_agent", "label": "Event", "role": "Find and filter local events"},
    {"id": "aggregator", "label": "Aggregator", "role": "Join parallel flight/hotel/event results"},
    {"id": "activity_extractor", "label": "Activities", "role": "Extract visitable places from search"},
    {"id": "geocoding_agent", "label": "Geocoding", "role": "Resolve place coordinates"},
    {"id": "scheduler", "label": "Scheduler", "role": "Build the day-by-day itinerary"},
    {"id": "evaluator", "label": "Evaluator", "role": "Audit budget and trigger refinements"},
    {"id": "map_generator", "label": "Map", "role": "Render the Folium trip map"},
    {"id": "report_formatter", "label": "Report", "role": "Write the markdown itinerary"},
]

AGENT_ORDER = [item["id"] for item in AGENT_CATALOG]
AGENT_LABELS = {item["id"]: item["label"] for item in AGENT_CATALOG}

_run_var: ContextVar[Optional["ActiveRun"]] = ContextVar("agent_run", default=None)
_agent_var: ContextVar[Optional[str]] = ContextVar("agent_name", default=None)
_tls = threading.local()
_RUNS: Dict[str, "ActiveRun"] = {}
_RUNS_LOCK = threading.Lock()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def normalize_model(name: Optional[str]) -> str:
    raw = (name or "").strip()
    lowered = raw.lower()
    if "gpt-5.6-luna" in lowered:
        return "gpt-5.6-luna"
    if "gpt-5.6-terra" in lowered:
        return "gpt-5.6-terra"
    if "gpt-5.6-sol" in lowered or lowered in {"gpt-5.6", "gpt-5.6-sol"}:
        return "gpt-5.6-sol"
    if lowered.startswith("gpt-4o-mini") or lowered == "gpt-4o-mini":
        return "gpt-4o-mini"
    if lowered.startswith("gpt-4o") and "mini" not in lowered:
        return "gpt-4o"
    if "gemini-2.5-flash" in lowered:
        return "gemini-2.5-flash"
    if "embedding-004" in lowered:
        return "text-embedding-004"
    return raw or "unknown"


def infer_provider(model_name: Optional[str]) -> str:
    pricing = PRICING.get(normalize_model(model_name))
    if pricing:
        return pricing["provider"]
    lowered = (model_name or "").lower()
    if "gemini" in lowered or "embedding" in lowered:
        return "google"
    if "gpt" in lowered or "openai" in lowered:
        return "openai"
    return "unknown"


def infer_model_name(runnable: Any) -> str:
    current = runnable
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        for attr in ("model_name", "model"):
            value = getattr(current, attr, None)
            if isinstance(value, str) and value and value not in {"model", "bound"}:
                return normalize_model(value)
        current = getattr(current, "bound", None)
    return "unknown"


def calc_cost_usd(model_name: Optional[str], input_tokens: int, output_tokens: int) -> float:
    pricing = PRICING.get(normalize_model(model_name))
    if not pricing:
        return 0.0
    return (
        (max(input_tokens, 0) / 1_000_000) * pricing["input_per_million"]
        + (max(output_tokens, 0) / 1_000_000) * pricing["output_per_million"]
    )


def usage_from_message(message: Any) -> tuple[int, int]:
    input_tokens = 0
    output_tokens = 0
    usage = getattr(message, "usage_metadata", None)
    if usage:
        if isinstance(usage, dict):
            input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
            output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        else:
            input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
            output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    meta = getattr(message, "response_metadata", None) or {}
    if isinstance(meta, dict):
        token_usage = meta.get("token_usage") or meta.get("usage") or {}
        if isinstance(token_usage, dict):
            if not input_tokens:
                input_tokens = int(token_usage.get("prompt_tokens") or token_usage.get("input_tokens") or 0)
            if not output_tokens:
                output_tokens = int(token_usage.get("completion_tokens") or token_usage.get("output_tokens") or 0)
    return input_tokens, output_tokens


def prompt_as_text(prompt: Any) -> str:
    if prompt is None:
        return ""
    if isinstance(prompt, str):
        return prompt
    content = getattr(prompt, "content", None)
    if isinstance(content, str):
        return content
    return str(prompt)


@dataclass
class Span:
    agent: str
    kind: str
    started_at: datetime
    duration_ms: float
    model: Optional[str] = None
    provider: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    status: str = "ok"
    error: Optional[str] = None
    extra: Optional[dict] = None


@dataclass
class ActiveRun:
    user_id: Any
    session_id: Optional[str]
    kind: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    route: Optional[str] = None
    started_at: datetime = field(default_factory=_utc_now)
    spans: List[Span] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    status: str = "ok"
    error: Optional[str] = None

    def add(self, span: Span) -> None:
        with self.lock:
            self.spans.append(span)


def current_run() -> Optional[ActiveRun]:
    return _run_var.get() or getattr(_tls, "run", None)


def current_agent() -> str:
    return _agent_var.get() or getattr(_tls, "agent", None) or "unknown"


def bind_run(run: Optional[ActiveRun]):
    token = _run_var.set(run)
    _tls.run = run
    return token


def bind_agent(name: Optional[str]):
    token = _agent_var.set(name)
    _tls.agent = name
    return token


def start_run(user_id, session_id: Optional[str], kind: str = "chat") -> ActiveRun:
    run = ActiveRun(user_id=user_id, session_id=str(session_id) if session_id else None, kind=kind)
    with _RUNS_LOCK:
        _RUNS[run.id] = run
    bind_run(run)
    return run


def run_from_state(state: Optional[dict]) -> Optional[ActiveRun]:
    if not isinstance(state, dict):
        return current_run()
    run_id = state.get("telemetry_run_id")
    if run_id:
        with _RUNS_LOCK:
            found = _RUNS.get(run_id)
        if found:
            return found
    return current_run()


def add_span(
    *,
    kind: str,
    duration_ms: float,
    agent: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
    status: str = "ok",
    error: Optional[str] = None,
    extra: Optional[dict] = None,
    started_at: Optional[datetime] = None,
) -> None:
    run = current_run()
    if not run:
        return
    agent_name = agent or current_agent()
    ended = _utc_now()
    start = started_at or (ended - timedelta(milliseconds=max(duration_ms, 0)))
    run.add(
        Span(
            agent=agent_name,
            kind=kind,
            started_at=start,
            duration_ms=max(duration_ms, 0),
            model=normalize_model(model) if model else None,
            provider=provider,
            input_tokens=int(input_tokens or 0),
            output_tokens=int(output_tokens or 0),
            cost_usd=float(cost_usd or 0),
            status=status,
            error=(error or "")[:500] or None,
            extra=extra,
        )
    )


@contextmanager
def agent_scope(name: str):
    run = current_run()
    agent_token = bind_agent(name)
    started = _utc_now()
    t0 = time.perf_counter()
    status = "ok"
    error = None
    try:
        yield
    except Exception as exc:
        status = "error"
        error = str(exc)[:500]
        raise
    finally:
        if run:
            run.add(
                Span(
                    agent=name,
                    kind="agent",
                    started_at=started,
                    duration_ms=(time.perf_counter() - t0) * 1000,
                    status=status,
                    error=error,
                )
            )
        try:
            _agent_var.reset(agent_token)
        except Exception:
            pass
        _tls.agent = _agent_var.get()


def timed_node(name: str, fn: Callable):
    def wrapper(state):
        run = run_from_state(state)
        run_token = bind_run(run) if run else None
        agent_token = bind_agent(name)
        started = _utc_now()
        t0 = time.perf_counter()
        status = "ok"
        error = None
        try:
            return fn(state)
        except Exception as exc:
            status = "error"
            error = str(exc)[:500]
            raise
        finally:
            if run:
                run.add(
                    Span(
                        agent=name,
                        kind="agent",
                        started_at=started,
                        duration_ms=(time.perf_counter() - t0) * 1000,
                        status=status,
                        error=error,
                    )
                )
            try:
                _agent_var.reset(agent_token)
            except Exception:
                pass
            _tls.agent = None
            if run_token is not None:
                try:
                    _run_var.reset(run_token)
                except Exception:
                    pass

    wrapper.__name__ = getattr(fn, "__name__", name)
    return wrapper

## đây là 1 hàm bọc wrapper để ghi lại các trường thông tin quan trọng dành cho LLM 
def tracked_invoke(runnable, prompt, *, model: Optional[str] = None, provider: Optional[str] = None):
    # Trích xuất tên mô hình
    model_name = normalize_model(model or infer_model_name(runnable))
    # Trích xuất tên provider
    provider_name = provider or infer_provider(model_name)
    # Trích xuất prompt text
    prompt_text = prompt_as_text(prompt)
    started = _utc_now()
    t0 = time.perf_counter()
    status = "ok"
    error = None
    message = None
    try:
        message = runnable.invoke(prompt)
        return message
    except Exception as exc:
        status = "error"
        error = str(exc)[:500]
        raise
    finally:
        duration_ms = (time.perf_counter() - t0) * 1000
        input_tokens = output_tokens = 0
        reported_input = 0
        if message is not None:
            reported_input, output_tokens = usage_from_message(message)
            input_tokens = reported_input
        if input_tokens <= 0:
            input_tokens = estimate_tokens(prompt_text)
        add_span(
            kind="llm",
            duration_ms=duration_ms,
            model=model_name,
            provider=provider_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=calc_cost_usd(model_name, input_tokens, output_tokens),
            status=status,
            error=error,
            extra={"estimated_input": reported_input <= 0},
            started_at=started,
        )


def tracked_post(url, **kwargs):
    started = _utc_now()
    t0 = time.perf_counter()
    status = "ok"
    error = None
    code = None
    try:
        response = requests.post(url, **kwargs)
        code = response.status_code
        if response.status_code >= 400:
            status = "error"
            error = f"HTTP {response.status_code}"
        return response
    except Exception as exc:
        status = "error"
        error = str(exc)[:500]
        raise
    finally:
        add_span(
            kind="http",
            duration_ms=(time.perf_counter() - t0) * 1000,
            status=status,
            error=error,
            extra={"url": url, "status_code": code},
            started_at=started,
        )


def record_embed(texts: List[str], duration_ms: float, status: str = "ok", error: Optional[str] = None) -> None:
    joined = " ".join(item for item in texts if item)
    input_tokens = estimate_tokens(joined)
    add_span(
        kind="embed",
        duration_ms=duration_ms,
        agent=current_agent() if current_agent() != "unknown" else "memory",
        model="text-embedding-004",
        provider="google",
        input_tokens=input_tokens,
        output_tokens=0,
        cost_usd=calc_cost_usd("text-embedding-004", input_tokens, 0),
        status=status,
        error=error,
        extra={"texts": len(texts)},
    )


def persist_run(db, run: Optional[ActiveRun], status: str = "ok", error: Optional[str] = None, route: Optional[str] = None) -> None:
    if run is None:
        return
    from db.models import AgentRunRow, AgentSpanRow

    run.status = status
    if error:
        run.error = error[:500]
    if route:
        run.route = route
    ended = _utc_now()
    with run.lock:
        spans = list(run.spans)

    input_tokens = sum(span.input_tokens for span in spans)
    output_tokens = sum(span.output_tokens for span in spans)
    cost_usd = sum(span.cost_usd for span in spans)
    llm_calls = sum(1 for span in spans if span.kind == "llm")
    http_calls = sum(1 for span in spans if span.kind == "http")
    duration_ms = (ended - run.started_at).total_seconds() * 1000

    session_uuid = None
    if run.session_id:
        try:
            session_uuid = uuid.UUID(str(run.session_id))
        except (ValueError, TypeError):
            session_uuid = None

    user_uuid = run.user_id
    if not isinstance(user_uuid, uuid.UUID):
        try:
            user_uuid = uuid.UUID(str(user_uuid))
        except (ValueError, TypeError):
            with _RUNS_LOCK:
                _RUNS.pop(run.id, None)
            return

    row = AgentRunRow(
        id=uuid.UUID(run.id),
        user_id=user_uuid,
        session_id=session_uuid,
        kind=run.kind,
        route=run.route,
        status=run.status,
        error=run.error,
        started_at=run.started_at,
        ended_at=ended,
        duration_ms=duration_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        llm_calls=llm_calls,
        http_calls=http_calls,
        cost_usd=cost_usd,
    )
    db.add(row)
    for span in spans:
        db.add(
            AgentSpanRow(
                run_id=row.id,
                agent=span.agent,
                kind=span.kind,
                model=span.model,
                provider=span.provider,
                status=span.status,
                error=span.error,
                started_at=span.started_at,
                duration_ms=span.duration_ms,
                input_tokens=span.input_tokens,
                output_tokens=span.output_tokens,
                cost_usd=span.cost_usd,
                extra=span.extra,
            )
        )
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        print(f"-> Failed to persist agent metrics: {exc}")
    finally:
        with _RUNS_LOCK:
            _RUNS.pop(run.id, None)
