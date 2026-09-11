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
    """Standalone metadata so agent-services do not import orchestrator db.base.

    Table shapes must match server/db/models.py (AgentFact / AgentWorking / AgentCache).
    Orchestrator init_db and this package's init_agent_db both create_all these tables.
    """


def utc_now() -> datetime:
    return datetime.now(timezone.utc)

# table agent_facts khóa (agent_id, user_id, text, embedding)
## agent_facts : đại diện cho user này trong nghề của tôi thích điều gì 
# Bộ nhớ agent_facts được lưu trữ trong database PostgreSQL, được truy hổi ngay trước khi LLM chạy
"""
Ngay đầu run_agent, trước khi LLM chạy:
facts = memory.retrieve_facts(request.user_id, query, limit=5)
working = memory.get_working(request.session_id)

Ví dụ: "Hanoi Da Nang hates overnight flights cheaper please".
 Embed câu đó, so cosine với mọi fact của user này + agent này, lấy top 5. 
 Không có embedding thì fallback fact mới nhất
"""
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


##AgentWorking — “danh sách vừa search, lựa chọn vừa pick”

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


"""
cache = sổ đổi tên (city → IATA / location id / tọa độ), không phải sổ kết quả search.
      = ổ quy đổi mã của từng hệ thống ngoài.
Mỗi API không search bằng chữ “Hà Nội” / “Đà Nẵng” mà bằng mã riêng của họ:

Vé máy bay → IATA (HAN, SGN)
Booking.com khách sạn → location_id của thành phố
Nominatim bản đồ → latitude / longitude

Đây là các bước quy đổi
chữ người dùng          bước 1: đổi tên           bước 2: search
──────────────          ────────────────          ──────────────
"Hà Nội"           →    HAN                       vé, giá, giờ bay
"Sài Gòn"          →    SGN
"Đà Nẵng"          →    location_id "xyz"         list khách sạn + giá
"Tháp Eiffel, Paris" →  48.85, 2.29               (vẽ map)
"""
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
