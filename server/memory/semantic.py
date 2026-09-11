"""
Sematic memory Là gì: kiến thức bền về người dùng, đúng ở mọi chat sau này.
Sematic memory gồm 2 bảng A và B.
Bảng A lưu profile của người dùng là 1 bảng gồm các field 
(home_city, preferred_language, budget_pref, interests, dietary, hotel_style, travel_pace)
Bảng B lưu các facts của người dùng(Câu ngắn không vừa field profile, 
kèm embedding 768 chiều (Gemini text-embedding-004) để tìm theo nghĩa)
"""




from typing import List, Optional

from sqlalchemy.orm import Session

from db.models import UserFact, UserProfile, utc_now
from memory.embed import embed_text
from memory.working import as_uuid

PROFILE_FIELDS = (
    "home_city",
    "preferred_language",
    "budget_pref",
    "interests",
    "dietary",
    "hotel_style",
    "travel_pace",
)


def get_or_create_profile(db: Session, user_id) -> UserProfile:
    uid = as_uuid(user_id)
    profile = db.query(UserProfile).filter(UserProfile.user_id == uid).first()
    if profile:
        return profile
    profile = UserProfile(user_id=uid)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def profile_as_dict(profile: Optional[UserProfile]) -> dict:
    if not profile:
        return {}
    data = {}
    for field in PROFILE_FIELDS:
        value = getattr(profile, field, None)
        if value not in (None, "", []):
            data[field] = value
    return data


def profile_as_text(profile: Optional[UserProfile]) -> str:
    data = profile_as_dict(profile)
    if not data:
        return ""
    lines = []
    labels = {
        "home_city": "Home city",
        "preferred_language": "Preferred language",
        "budget_pref": "Typical budget",
        "interests": "Interests",
        "dietary": "Dietary needs",
        "hotel_style": "Hotel style",
        "travel_pace": "Travel pace",
    }
    for key, label in labels.items():
        value = data.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value)
        lines.append(f"{label}: {value}")
    return "\n".join(lines)


def apply_profile_updates(db: Session, user_id, updates: dict) -> UserProfile:
    profile = get_or_create_profile(db, as_uuid(user_id))
    changed = False
    for field in PROFILE_FIELDS:
        if field not in updates or updates[field] is None:
            continue
        value = updates[field]
        if value == "" or value == []:
            continue
        if field == "interests" and isinstance(value, list):
            existing = list(profile.interests or [])
            merged = list(dict.fromkeys([*existing, *[str(item) for item in value if item]]))
            if merged != existing:
                profile.interests = merged
                changed = True
            continue
        if getattr(profile, field) != value:
            setattr(profile, field, value)
            changed = True
    if changed:
        profile.updated_at = utc_now()
        db.commit()
        db.refresh(profile)
    return profile


def add_facts(db: Session, user_id, facts: List[str], source_session_id=None) -> None:
    uid = as_uuid(user_id)
    session_uuid = as_uuid(source_session_id) if source_session_id else None
    added = False
    for raw in facts or []:
        text = (raw or "").strip()
        if not text:
            continue
        existing = (
            db.query(UserFact)
            .filter(UserFact.user_id == uid, UserFact.text == text)
            .first()
        )
        if existing:
            continue
        db.add(
            UserFact(
                user_id=uid,
                text=text,
                embedding=embed_text(text),
                source_session_id=session_uuid,
            )
        )
        added = True
    if added:
        db.commit()


def retrieve_facts(db: Session, user_id, query: str, limit: int = 5) -> List[str]:
    uid = as_uuid(user_id)
    rows = db.query(UserFact).filter(UserFact.user_id == uid).all()
    if not rows:
        return []
    vector = embed_text(query) if query else None
    if vector is None:
        rows.sort(key=lambda item: item.created_at or utc_now(), reverse=True)
        return [item.text for item in rows[:limit]]
    scored = []
    for item in rows:
        if item.embedding is None:
            scored.append((0.0, item))
            continue
        scored.append((-_cosine_distance(vector, list(item.embedding)), item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item.text for _, item in scored[:limit]]


def _cosine_distance(left: List[float], right: List[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 1.0
    dot = sum(a * b for a, b in zip(left, right))
    norm_l = sum(a * a for a in left) ** 0.5
    norm_r = sum(b * b for b in right) ** 0.5
    if not norm_l or not norm_r:
        return 1.0
    return 1.0 - (dot / (norm_l * norm_r))
