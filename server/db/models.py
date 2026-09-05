import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base

EMBEDDING_DIM = 768


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    sessions: Mapped[List["ChatSessionRow"]] = relationship(back_populates="user")
    profile: Mapped[Optional["UserProfile"]] = relationship(back_populates="user", uselist=False)


class ChatSessionRow(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(160), default="New chat")
    language: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    has_plan: Mapped[bool] = mapped_column(default=False)
    user_feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    slots: Mapped[dict] = mapped_column(JSONB, default=dict)
    trip_state: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    markdown_report: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    user: Mapped["User"] = relationship(back_populates="sessions")
    messages: Mapped[List["Message"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="Message.created_at"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text, default="")
    extra: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    position: Mapped[int] = mapped_column(default=0)

    session: Mapped["ChatSessionRow"] = relationship(back_populates="messages")


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    home_city: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    preferred_language: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    budget_pref: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    interests: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    dietary: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    hotel_style: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    travel_pace: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    user: Mapped["User"] = relationship(back_populates="profile")


class UserFact(Base):
    __tablename__ = "user_facts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    source_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Episode(Base):
    __tablename__ = "episodes"
    __table_args__ = (UniqueConstraint("user_id", "session_id", name="uq_episode_user_session"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    summary: Mapped[str] = mapped_column(Text)
    destination: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    start_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    end_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    embedding = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class AgentFact(Base):
    """Domain preference for one user inside one agent (flight/hotel/...). Not traveler profile.

    Keep columns in sync with packages.agent_runtime.models.AgentFact so service create_all
    and orchestrator init_db produce the same tables.
    """

    __tablename__ = "agent_facts"
    __table_args__ = (Index("ix_agent_facts_agent_user", "agent_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    text: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentWorking(Base):
    """Per-session scratch pad for one agent. Refine uses this list; it is not a durable fact.

    Keep columns in sync with packages.agent_runtime.models.AgentWorking.
    """

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


class AgentCache(Base):
    """Shared lookup cache, not tied to a user (IATA, lat/lon, location ids).

    Keep columns in sync with packages.agent_runtime.models.AgentCache.
    """

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


class AgentRunRow(Base):
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), default="chat")
    route: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ok")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[float] = mapped_column(Float, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    http_calls: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0)
    extra: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    spans: Mapped[List["AgentSpanRow"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class AgentSpanRow(Base):
    __tablename__ = "agent_spans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    agent: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(32), default="agent")
    model: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    provider: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ok")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    duration_ms: Mapped[float] = mapped_column(Float, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0)
    extra: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    run: Mapped["AgentRunRow"] = relationship(back_populates="spans")

