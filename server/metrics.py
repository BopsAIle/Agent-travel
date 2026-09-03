from typing import Dict, List, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from db.models import AgentRunRow, AgentSpanRow
from telemetry import AGENT_CATALOG, AGENT_LABELS, AGENT_ORDER, PRICING


def _iso(value) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _run_payload(row: AgentRunRow) -> dict:
    return {
        "id": str(row.id),
        "session_id": str(row.session_id) if row.session_id else None,
        "kind": row.kind,
        "route": row.route,
        "status": row.status,
        "error": row.error,
        "started_at": _iso(row.started_at),
        "ended_at": _iso(row.ended_at),
        "duration_ms": row.duration_ms or 0,
        "input_tokens": row.input_tokens or 0,
        "output_tokens": row.output_tokens or 0,
        "llm_calls": row.llm_calls or 0,
        "http_calls": row.http_calls or 0,
        "cost_usd": float(row.cost_usd or 0),
    }


def _span_payload(row: AgentSpanRow) -> dict:
    return {
        "id": str(row.id),
        "agent": row.agent,
        "label": AGENT_LABELS.get(row.agent, row.agent.replace("_", " ").title()),
        "kind": row.kind,
        "model": row.model,
        "provider": row.provider,
        "status": row.status,
        "error": row.error,
        "started_at": _iso(row.started_at),
        "duration_ms": row.duration_ms or 0,
        "input_tokens": row.input_tokens or 0,
        "output_tokens": row.output_tokens or 0,
        "cost_usd": float(row.cost_usd or 0),
        "extra": row.extra or {},
    }


def _empty_agent(agent_id: str) -> dict:
    label = AGENT_LABELS.get(agent_id, agent_id.replace("_", " ").title())
    role = next((item["role"] for item in AGENT_CATALOG if item["id"] == agent_id), "")
    return {
        "agent": agent_id,
        "label": label,
        "role": role,
        "calls": 0,
        "duration_ms": 0.0,
        "avg_ms": 0.0,
        "max_ms": 0.0,
        "llm_calls": 0,
        "http_calls": 0,
        "embed_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
        "errors": 0,
    }


def agent_metrics_overview(db: Session, user_id, limit_runs: int = 40) -> dict:
    runs: List[AgentRunRow] = (
        db.query(AgentRunRow)
        .filter(AgentRunRow.user_id == user_id)
        .order_by(desc(AgentRunRow.started_at))
        .limit(limit_runs)
        .all()
    )
    run_ids = [row.id for row in runs]
    spans: List[AgentSpanRow] = []
    if run_ids:
        spans = db.query(AgentSpanRow).filter(AgentSpanRow.run_id.in_(run_ids)).all()

    by_agent: Dict[str, dict] = {item["id"]: _empty_agent(item["id"]) for item in AGENT_CATALOG}

    for span in spans:
        stats = by_agent.setdefault(span.agent, _empty_agent(span.agent))
        if span.kind == "agent":
            stats["calls"] += 1
            stats["duration_ms"] += span.duration_ms or 0
            stats["max_ms"] = max(stats["max_ms"], span.duration_ms or 0)
            if span.status != "ok":
                stats["errors"] += 1
        elif span.kind == "llm":
            stats["llm_calls"] += 1
            stats["input_tokens"] += span.input_tokens or 0
            stats["output_tokens"] += span.output_tokens or 0
            stats["cost_usd"] += float(span.cost_usd or 0)
            if span.status != "ok":
                stats["errors"] += 1
        elif span.kind == "http":
            stats["http_calls"] += 1
            if span.status != "ok":
                stats["errors"] += 1
        elif span.kind == "embed":
            stats["embed_calls"] += 1
            stats["input_tokens"] += span.input_tokens or 0
            stats["cost_usd"] += float(span.cost_usd or 0)
            if span.status != "ok":
                stats["errors"] += 1

    agents = []
    seen = set()
    for agent_id in AGENT_ORDER:
        stats = by_agent[agent_id]
        seen.add(agent_id)
        stats["avg_ms"] = (stats["duration_ms"] / stats["calls"]) if stats["calls"] else 0
        agents.append(stats)
    for agent_id, stats in by_agent.items():
        if agent_id in seen:
            continue
        stats["avg_ms"] = (stats["duration_ms"] / stats["calls"]) if stats["calls"] else 0
        agents.append(stats)

    summary = {
        "runs": len(runs),
        "duration_ms": sum(row.duration_ms or 0 for row in runs),
        "cost_usd": sum(float(row.cost_usd or 0) for row in runs),
        "input_tokens": sum(row.input_tokens or 0 for row in runs),
        "output_tokens": sum(row.output_tokens or 0 for row in runs),
        "llm_calls": sum(row.llm_calls or 0 for row in runs),
        "http_calls": sum(row.http_calls or 0 for row in runs),
        "errors": sum(1 for row in runs if row.status != "ok"),
    }

    return {
        "summary": summary,
        "agents": agents,
        "runs": [_run_payload(row) for row in runs],
        "pricing": [
            {
                "model": model,
                "provider": meta["provider"],
                "input_per_million": meta["input_per_million"],
                "output_per_million": meta["output_per_million"],
                "note": meta["note"],
            }
            for model, meta in PRICING.items()
        ],
        "catalog": AGENT_CATALOG,
    }


def agent_run_detail(db: Session, user_id, run_id) -> Optional[dict]:
    row = (
        db.query(AgentRunRow)
        .filter(AgentRunRow.user_id == user_id, AgentRunRow.id == run_id)
        .first()
    )
    if not row:
        return None
    spans = (
        db.query(AgentSpanRow)
        .filter(AgentSpanRow.run_id == row.id)
        .order_by(AgentSpanRow.started_at.asc())
        .all()
    )
    return {
        "run": _run_payload(row),
        "spans": [_span_payload(span) for span in spans],
    }
