"""Dang ky, dang nhap, thong tin nguoi dung hien tai."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import (
    create_access_token,
    get_current_user,
    get_user_by_email,
    hash_password,
    verify_password,
)
from app.db.models import User
from app.db.session import get_db
from app.memory.semantic import get_or_create_profile
from app.schemas import AuthRequest, AuthResponse

router = APIRouter(prefix="/auth", tags=["auth"])


def _auth_payload(user: User) -> AuthResponse:
    return AuthResponse(
        access_token=create_access_token(user),
        user_id=str(user.id),
        email=user.email,
    )


@router.post("/register", response_model=AuthResponse)
def register(payload: AuthRequest, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Invalid email.")
    if get_user_by_email(db, email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered.")
    user = User(email=email, password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    get_or_create_profile(db, user.id)
    return _auth_payload(user)


@router.post("/login", response_model=AuthResponse)
def login(payload: AuthRequest, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    user = get_user_by_email(db, email)
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")
    return _auth_payload(user)


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"user_id": str(user.id), "email": user.email}
