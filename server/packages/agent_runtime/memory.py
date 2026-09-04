from __future__ import annotations

import json
import uuid
from typing import Any, Callable, List, Optional

from sqlalchemy.orm import Session

from .embed import embed_text
from .models import AgentCache, AgentFact, AgentWorking, utc_now


def as_uuid(value) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def normalize_cache_key(key: str) -> str:
    return " ".join((key or "").strip().lower().split())


def _cosine_similarity(left: List[float], right: List[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norm_l = sum(a * a for a in left) ** 0.5
    norm_r = sum(b * b for b in right) ** 0.5
    if not norm_l or not norm_r:
        return 0.0
    return dot / (norm_l * norm_r)


def jsonable(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    if isinstance(value, uuid.UUID):
        return str(value)
    return value

##Mỗi agent service có 1 đối tượng riêng DomainMemory và gọi 3 loại memory
## 3 loại memory đó là :
"""
1. AgentFact: lưu trữ các fact liên quan đến user
2. AgentWorking: lưu trữ các working liên quan đến session hiện tại
3. AgentCache: lưu trữ các cache dùng chung cho các user(nếu cùng 1 câu hỏi và môi trường giữa các user
thì việc sử dụng lại AgentCache là điều đúng đắn)
"""
class DomainMemory:
    """Domain memory for one agent_id. Traveler profile stays on the orchestrator."""

    def __init__(self, db: Optional[Session], agent_id: str, hits: Optional[List[str]] = None):
        self.db = db
        self.agent_id = agent_id
        self.hits = hits if hits is not None else []

    def _hit(self, item: str) -> None:
        if item and item not in self.hits:
            self.hits.append(item)
    
    ## Truy hồi thông tin liên quan đến user từ bộ nhớ fact 
    def retrieve_facts(self, user_id, query: str, limit: int = 5) -> List[str]:
        if self.db is None:
            return []
        uid = as_uuid(user_id)
        rows = (
            self.db.query(AgentFact)
            .filter(AgentFact.agent_id == self.agent_id, AgentFact.user_id == uid)
            .all()
        )
        if not rows:
            return []
        vector = embed_text(query) if query else None
        if vector is None:
            rows.sort(key=lambda item: item.created_at or utc_now(), reverse=True)
            texts = [item.text for item in rows[:limit]]
        else:
            scored = []
            for item in rows:
                if item.embedding is None:
                    scored.append((0.0, item))
                    continue
                scored.append((_cosine_similarity(vector, list(item.embedding)), item))
            scored.sort(key=lambda pair: pair[0], reverse=True)
            texts = [item.text for _, item in scored[:limit]]
        for text in texts:
            preview = text if len(text) <= 80 else text[:77] + "..."
            self._hit(f"fact:{preview}")
        return texts
    
    # Thêm thông tin liên quan đến user vào bộ nhớ fact 
    def add_facts(self, user_id, facts: List[str]) -> int:
        if self.db is None:
            return 0
        uid = as_uuid(user_id)
        added = 0
        for raw in facts or []:
            text = (raw or "").strip()
            if not text:
                continue
            existing = (
                self.db.query(AgentFact)
                .filter(
                    AgentFact.agent_id == self.agent_id,
                    AgentFact.user_id == uid,
                    AgentFact.text == text,
                )
                .first()
            )
            if existing:
                continue
            self.db.add(
                AgentFact(
                    agent_id=self.agent_id,
                    user_id=uid,
                    text=text,
                    embedding=embed_text(text),
                )
            )
            added += 1
        if added:
            self.db.commit()
        return added

    def get_working(self, session_id) -> Optional[dict]:
        if self.db is None:
            return None
        sid = as_uuid(session_id)
        row = (
            self.db.query(AgentWorking)
            .filter(AgentWorking.agent_id == self.agent_id, AgentWorking.session_id == sid)
            .first()
        )
        if not row:
            return None
        self._hit(f"working:{sid}")
        return dict(row.payload or {})

    def set_working(self, session_id, payload: dict) -> None:
        if self.db is None:
            return
        sid = as_uuid(session_id)
        row = (
            self.db.query(AgentWorking)
            .filter(AgentWorking.agent_id == self.agent_id, AgentWorking.session_id == sid)
            .first()
        )
        data = jsonable(payload) or {}
        if row:
            row.payload = data
            row.updated_at = utc_now()
        else:
            self.db.add(
                AgentWorking(agent_id=self.agent_id, session_id=sid, payload=data)
            )
        self.db.commit()

    def get_cache(self, key: str) -> Optional[Any]:
        if self.db is None:
            return None
        cache_key = normalize_cache_key(key)
        if not cache_key:
            return None
        row = (
            self.db.query(AgentCache)
            .filter(AgentCache.agent_id == self.agent_id, AgentCache.cache_key == cache_key)
            .first()
        )
        if row is None:
            return None
        self._hit(cache_key)
        return row.value

    def set_cache(self, key: str, value: Any) -> None:
        if self.db is None:
            return
        cache_key = normalize_cache_key(key)
        if not cache_key:
            return
        row = (
            self.db.query(AgentCache)
            .filter(AgentCache.agent_id == self.agent_id, AgentCache.cache_key == cache_key)
            .first()
        )
        data = jsonable(value)
        if row:
            row.value = data
            row.updated_at = utc_now()
        else:
            self.db.add(AgentCache(agent_id=self.agent_id, cache_key=cache_key, value=data))
        self.db.commit()

    def get_or_set_cache(self, key: str, factory: Callable[[], Any]) -> Any:
        hit = self.get_cache(key)
        if hit is not None:
            return hit
        value = factory()
        self.set_cache(key, value)
        return value

    def facts_block(self, facts: List[str]) -> str:
        if not facts:
            return "(none)"
        return "\n".join(f"- {item}" for item in facts)

    def working_block(self, payload: Optional[dict]) -> str:
        if not payload:
            return "(none)"
        try:
            return json.dumps(payload, ensure_ascii=False, default=str)[:4000]
        except TypeError:
            return str(payload)[:4000]
