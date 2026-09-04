### model.py : có 3 memory AgentFact, AgentWorking, AgentCache được lưu trữ trong database PostgreSQL

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, String, Text, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 768


class AgentRuntimeBase(DeclarativeBase):
    """Standalone metadata so agent-services do not import orchestrator db.base."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)

#
class AgentFact(AgentRuntimeBase):
    """Durable domain preference for one user inside one agent (e.g. prefers direct)."""

    __tablename__ = "agent_facts"
    __table_args__ = (Index("ix_agent_facts_agent_user", "agent_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    text: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentWorking(AgentRuntimeBase):
    """Per-session scratch pad: last search list, current pick. Not a durable fact."""

    __tablename__ = "agent_working"
    __table_args__ = (
        UniqueConstraint("agent_id", "session_id", name="uq_agent_working_agent_session"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[str] = mapped_column(String(32), index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class AgentCache(AgentRuntimeBase):
    """Shared lookup cache, not tied to a user (IATA codes, lat/lon, location ids)."""

    __tablename__ = "agent_cache"
    __table_args__ = (
        UniqueConstraint("agent_id", "cache_key", name="uq_agent_cache_agent_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[str] = mapped_column(String(32), index=True)
    cache_key: Mapped[str] = mapped_column(String(255))
    value: Mapped[Any] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
