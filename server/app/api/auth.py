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

# POST /auth/register : Người dùng gửi yêu cầu đăng nhập với email và password
#response_model : FastAPI sẽ lọc và trả về đúng theo khuôn AuthResponse
"""
db: Session = Depends(get_db): Depends(get_db) muốn bảo với fastAPI rằng hãy gọi hàm get_db() 
và gán vào biến db trước khi thực hiện hàm register
"""
@router.post("/register", response_model=AuthResponse)
def register(payload: AuthRequest, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Invalid email.")
    #Kiểm tra email đã tồn tại hay chưa : get_user_by_email ; Nếu tồn tại rồi thì bỏ đi
    if get_user_by_email(db, email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered.")
    #Tạo user {Pydantic mới với email và password đã hash
    user = User(email=email, password_hash=hash_password(payload.password))
    #Thêm user vào db
    db.add(user)
    db.commit()
    db.refresh(user)
    #Tạo profile cho user mới. Profile gồm(home_city, preferred_language, budget_pref, interests, dietary, hotel_style, travel_pace)
    get_or_create_profile(db, user.id) 
    # Trả về đối tượng AuthResponse với access_token, user_id, email
    return _auth_payload(user)


@router.post("/login", response_model=AuthResponse)
def login(payload: AuthRequest, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    user = get_user_by_email(db, email)
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")
    return _auth_payload(user)

## Hàm này:"token của tôi cầm còn sài được không? và tôi là ai"
"""
API này để hiểu: 
Token nằm trong LocalStorage,sống qua nhiều ngày.Khi user quay lại sau 
2 tuần,client không biết token này còn dùng được hay không. JWT ở phía server và client không khớp nữa
Do đó, cần API GET /auth/me để kiểm tra token còn hợp lệ hay không và trả về thông tin user hiện tại
"""
@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"user_id": str(user.id), "email": user.email}
