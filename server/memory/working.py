"""
Working memory:bộ nhớ ngắn hạn của một phiên chat.
Mất khi đóng chat (vẫn còn trong DB của session đó,
nhưng không lan sang chat khác trừ khi retrieve episode).
Bảng: sessions + messages

Bộ nhớ working memoryLưu:
lịch sử tin nhắn
slots: origin, destination, dates, budget, số người… của chuyến đang nói
trip_state: snapshot graph (vé đã chọn, khách sạn, itinerary)
has_plan, markdown_report, ngôn ngữ
"""



import uuid
from typing import Any, List, Optional

from sqlalchemy.orm import Session, selectinload

from conversation import ChatSession, session_summary, session_title, slots_snapshot
from db.models import ChatSessionRow, Message, utc_now
from schemas import (
    Activity,
    EvaluationResult,
    EventInfo,
    FlightInfo,
    HotelInfo,
    Itinerary,
    TripRequest,
)


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


def _hydrate_model(schema, payload):
    if not payload:
        return None
    if hasattr(payload, "model_dump"):
        return payload
    try:
        return schema(**payload)
    except Exception:
        return payload


def hydrate_trip_state(raw: Optional[dict]) -> Optional[dict]:
    if not raw:
        return None
    state = dict(raw)
    state["trip_plan"] = _hydrate_model(TripRequest, state.get("trip_plan"))
    state["selected_flight"] = _hydrate_model(FlightInfo, state.get("selected_flight"))
    state["selected_hotel"] = _hydrate_model(HotelInfo, state.get("selected_hotel"))
    state["final_itinerary"] = _hydrate_model(Itinerary, state.get("final_itinerary"))
    state["evaluation_result"] = _hydrate_model(EvaluationResult, state.get("evaluation_result"))
    if state.get("flight_options"):
        state["flight_options"] = [
            _hydrate_model(FlightInfo, item) or item for item in state["flight_options"]
        ]
    if state.get("hotel_options"):
        state["hotel_options"] = [
            _hydrate_model(HotelInfo, item) or item for item in state["hotel_options"]
        ]
    if state.get("extracted_activities"):
        state["extracted_activities"] = [
            _hydrate_model(Activity, item) or item for item in state["extracted_activities"]
        ]
    if state.get("events"):
        state["events"] = [_hydrate_model(EventInfo, item) or item for item in state["events"]]
    return state


def as_uuid(value) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _row_to_session(row: ChatSessionRow) -> ChatSession:
    messages = []
    ordered = sorted(row.messages or [], key=lambda item: (item.position, item.created_at))
    for item in ordered:
        payload = {"role": item.role, "content": item.content or ""}
        if item.extra:
            payload.update(item.extra)
        messages.append(payload)
    return ChatSession(
        session_id=str(row.id),
        user_id=str(row.user_id),
        messages=messages,
        slots=dict(row.slots or {}),
        language=row.language,
        trip_state=hydrate_trip_state(row.trip_state),
        user_feedback=row.user_feedback,
        has_plan=bool(row.has_plan),
        created_at=row.created_at.isoformat() if row.created_at else None,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
        markdown_report=row.markdown_report,
    )


def load_session(db: Session, user_id, session_id: str) -> Optional[ChatSession]:
    try:
        sid = as_uuid(session_id)
        uid = as_uuid(user_id)
    except (ValueError, TypeError):
        return None
    row = (
        db.query(ChatSessionRow)
        .options(selectinload(ChatSessionRow.messages))
        .filter(ChatSessionRow.id == sid, ChatSessionRow.user_id == uid)
        .first()
    )
    if not row:
        return None
    return _row_to_session(row)


def get_or_create_session(db: Session, user_id, session_id: Optional[str] = None) -> ChatSession:
    uid = as_uuid(user_id)
    if session_id:
        existing = load_session(db, uid, session_id)
        if existing:
            return existing
        try:
            sid = as_uuid(session_id)
        except (ValueError, TypeError):
            sid = uuid.uuid4()
        occupied = db.query(ChatSessionRow).filter(ChatSessionRow.id == sid).first()
        if occupied:
            sid = uuid.uuid4()
    else:
        sid = uuid.uuid4()

    row = ChatSessionRow(id=sid, user_id=uid, slots={}, title="New chat")
    db.add(row)
    db.commit()
    db.refresh(row)
    return _row_to_session(row)


def save_session(db: Session, session: ChatSession) -> None:
    uid = as_uuid(session.user_id)
    sid = as_uuid(session.session_id)
    row = (
        db.query(ChatSessionRow)
        .filter(ChatSessionRow.id == sid, ChatSessionRow.user_id == uid)
        .first()
    )
    if not row:
        row = ChatSessionRow(id=sid, user_id=uid)
        db.add(row)

    row.slots = dict(session.slots or {})
    row.language = session.language
    row.has_plan = bool(session.has_plan)
    row.user_feedback = session.user_feedback
    row.trip_state = jsonable(session.trip_state) if session.trip_state else None
    row.markdown_report = session.markdown_report or (
        (session.trip_state or {}).get("markdown_report") if session.trip_state else None
    )
    row.title = session_title(session.slots, session.messages)
    row.updated_at = utc_now()

    db.query(Message).filter(Message.session_id == sid, Message.user_id == uid).delete(
        synchronize_session=False
    )
    for index, item in enumerate(session.messages or []):
        extra = {
            key: value
            for key, value in item.items()
            if key not in ("role", "content")
        }
        db.add(
            Message(
                session_id=sid,
                user_id=uid,
                role=item.get("role") or "assistant",
                content=str(item.get("content") or ""),
                extra=extra or None,
                position=index,
            )
        )
    db.commit()
    session.updated_at = row.updated_at.isoformat() if row.updated_at else session.updated_at


def list_session_summaries(db: Session, user_id) -> List[dict]:
    uid = as_uuid(user_id)
    rows = (
        db.query(ChatSessionRow)
        .options(selectinload(ChatSessionRow.messages))
        .filter(ChatSessionRow.user_id == uid)
        .order_by(ChatSessionRow.updated_at.desc())
        .all()
    )
    items = []
    for row in rows:
        session = _row_to_session(row)
        if not session.messages:
            continue
        items.append(session_summary(session))
    return items


def export_session(session: ChatSession) -> dict:
    summary = session_summary(session)
    trip_state = session.trip_state or {}
    map_html = trip_state.get("map_html") if isinstance(trip_state, dict) else None
    summary.update(
        {
            "messages": session.messages,
            "slots": slots_snapshot(session.slots),
            "language": session.language,
            "markdown_report": session.markdown_report
            or (trip_state.get("markdown_report") if isinstance(trip_state, dict) else None),
            "map_html": map_html,
        }
    )
    return summary


def delete_session(db: Session, user_id, session_id: str) -> bool:
    try:
        uid = as_uuid(user_id)
        sid = as_uuid(session_id)
    except (ValueError, TypeError):
        return False
    row = (
        db.query(ChatSessionRow)
        .filter(ChatSessionRow.id == sid, ChatSessionRow.user_id == uid)
        .first()
    )
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True


def restore_session(
    db: Session,
    user_id,
    session_id: str,
    messages: List[dict],
    slots: Optional[dict] = None,
    language: Optional[str] = None,
    has_plan: bool = False,
) -> ChatSession:
    session = get_or_create_session(db, user_id, session_id)
    text_messages = []
    for item in messages or []:
        role = item.get("role")
        content = item.get("content")
        extra = {key: value for key, value in item.items() if key not in ("role", "content")}
        if role in ("user", "assistant", "itinerary"):
            payload = {"role": role, "content": content or ""}
            payload.update(extra)
            text_messages.append(payload)
    session.messages = text_messages
    if slots:
        session.slots = dict(slots)
    if language:
        session.language = language
    session.has_plan = has_plan
    save_session(db, session)
    return session
