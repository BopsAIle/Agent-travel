"""CRUD lich su hoi thoai (working memory) cua nguoi dung."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.memory.working import (
    delete_session,
    export_session,
    list_session_summaries,
    load_session,
    restore_session,
)
from app.schemas import RestoreChatRequest

router = APIRouter(prefix="/chats", tags=["chats"])


@router.get("")
def list_chats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"chats": list_session_summaries(db, user.id)}


@router.get("/{session_id}")
def get_chat(session_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    session = load_session(db, user.id, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat not found.")
    return export_session(session)


@router.put("/{session_id}")
def put_chat(
    session_id: str,
    request: RestoreChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = restore_session(
        db,
        user.id,
        session_id,
        request.messages,
        request.slots,
        request.language,
        request.has_plan,
    )
    return export_session(session)


@router.delete("/{session_id}")
def remove_chat(session_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not delete_session(db, user.id, session_id):
        raise HTTPException(status_code=404, detail="Chat not found.")
    return {"ok": True}
