"""
Episodic memory Là gì: kiến thức về chuyến đi cụ thể.
Episodic memory gồm bảng Episode.
Bảng Episode lưu các thông tin của chuyến đi cụ thể.
(summary, destination, start_date, end_date, embedding)
Summary là tóm tắt của chuyến đi.
Destination là điểm đến của chuyến đi.
Start date là ngày khởi hành của chuyến đi.
End date là ngày kết thúc của chuyến đi.
Embedding là embedding 768 chiều (Gemini text-embedding-004) của summary.

 embed câu hiện tại, lấy top 3 episode gần nghĩa. 
 User hỏi “lần trước mình đi đâu?” → intent recall, bot trả lời từ đây, không bịa.
"""



from typing import List, Optional

from sqlalchemy.orm import Session

from conversation import ChatSession, _itinerary_digest
from db.models import Episode, utc_now
from memory.embed import embed_text
from memory.working import as_uuid


def _episode_summary(session: ChatSession) -> str:
    slots = session.slots or {}
    origin = slots.get("origin") or "unknown origin"
    destination = slots.get("destination") or "unknown destination"
    start = slots.get("start_date") or "?"
    end = slots.get("end_date") or "?"
    interests = slots.get("interests")
    if isinstance(interests, list):
        interests = ", ".join(interests)
    digest = _itinerary_digest(session.trip_state)
    parts = [
        f"Trip from {origin} to {destination} ({start} to {end}).",
        digest,
    ]
    if interests:
        parts.append(f"Interests: {interests}.")
    if slots.get("budget") is not None:
        parts.append(f"Budget: {slots.get('budget')}.")
    return " ".join(parts)


def upsert_episode(db: Session, session: ChatSession) -> Optional[Episode]:
    if not session.has_plan:
        return None
    uid = as_uuid(session.user_id)
    sid = as_uuid(session.session_id)
    summary = _episode_summary(session)
    destination = (session.slots or {}).get("destination")
    start_date = (session.slots or {}).get("start_date")
    end_date = (session.slots or {}).get("end_date")
    vector = embed_text(summary)

    row = (
        db.query(Episode)
        .filter(Episode.user_id == uid, Episode.session_id == sid)
        .first()
    )
    if row:
        row.summary = summary
        row.destination = destination
        row.start_date = start_date
        row.end_date = end_date
        row.embedding = vector
        row.updated_at = utc_now()
    else:
        row = Episode(
            user_id=uid,
            session_id=sid,
            summary=summary,
            destination=destination,
            start_date=start_date,
            end_date=end_date,
            embedding=vector,
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    return row


def retrieve_episodes(db: Session, user_id, query: str, limit: int = 3) -> List[dict]:
    uid = as_uuid(user_id)
    rows = db.query(Episode).filter(Episode.user_id == uid).all()
    if not rows:
        return []
    vector = embed_text(query) if query else None

    def as_dict(item: Episode) -> dict:
        return {
            "summary": item.summary,
            "destination": item.destination,
            "start_date": item.start_date,
            "end_date": item.end_date,
            "session_id": str(item.session_id),
        }

    if vector is None:
        rows.sort(key=lambda item: item.updated_at or item.created_at, reverse=True)
        return [as_dict(item) for item in rows[:limit]]

    from memory.semantic import _cosine_distance

    scored = []
    for item in rows:
        if item.embedding is None:
            scored.append((0.0, item))
            continue
        scored.append((-_cosine_distance(vector, list(item.embedding)), item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [as_dict(item) for _, item in scored[:limit]]
