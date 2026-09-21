"""Chuan hoa va loc fact cua memory — thuan tuy, khong cham DB/LLM.

Hai van de that da xay ra duoc chan o day:

1. **Fact rac 1 ky tu.** LLM co the tra `facts_to_remember` la mot string thay vi
   list; neu code lam `list(string)` thi moi KY TU thanh mot fact. Da xay ra that:
   ~110 dong `agent_facts` dai dung 1 ky tu tao ngay 20/09, va chung van duoc nap
   vao prompt (`fact:ể`, `fact:,` trong log orchestrator).

2. **Fact cua chuyen khac lot vao chuyen hien tai.** `agent_facts` chi scope theo
   (agent_id, user_id), nen "uu tien khach san gan trung tam London" duoc nap vao
   ke hoach Seoul chi vi cung mot user.

Module nay khong import gi nang de test offline duoc.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, List, Optional

MIN_FACT_CHARS = 8
MAX_FACT_CHARS = 400
MAX_FACTS_PER_CALL = 5

# Ten thanh pho da biet, viet o dang DA BO DAU + CHU THUONG.
# Dung de nhan ra mot fact dang noi ve DIEM DEN KHAC — ke ca cac dong cu chua kip
# gan cot `destination` (truong hop "khach san gan trung tam London").
KNOWN_DESTINATIONS = (
    "hanoi", "ha noi", "ho chi minh", "hochiminh", "saigon", "sai gon",
    "danang", "da nang", "phu quoc", "nha trang", "hue", "can tho", "hai phong",
    "seoul", "busan", "jeju", "tokyo", "osaka", "kyoto", "sapporo",
    "hong kong", "hongkong", "macau", "taipei", "beijing", "shanghai",
    "guangzhou", "shenzhen", "chongqing", "trung khanh",
    "bangkok", "phuket", "chiang mai", "singapore", "singapo", "kuala lumpur",
    "jakarta", "bali", "manila", "yangon", "phnom penh",
    "paris", "london", "rome", "milan", "venice", "barcelona", "madrid",
    "lisbon", "amsterdam", "brussels", "berlin", "frankfurt", "munich",
    "zurich", "geneva", "vienna", "prague", "budapest", "warsaw",
    "copenhagen", "stockholm", "oslo", "helsinki", "dublin", "edinburgh",
    "athens", "istanbul", "cairo", "dubai", "doha", "riyadh", "tel aviv",
    "new york", "nyc", "los angeles", "san francisco", "chicago", "boston",
    "seattle", "miami", "las vegas", "washington", "toronto", "vancouver",
    "mexico city", "sao paulo", "rio de janeiro", "buenos aires",
    "sydney", "melbourne", "brisbane", "auckland", "moscow", "st petersburg",
    "delhi", "mumbai", "bangalore", "colombo", "kathmandu",
)

_SPLIT = re.compile(r"[,/|]")


def fold(text: str) -> str:
    """Bo dau + chu thuong, de 'Seoul' va 'seoul' so sanh duoc voi nhau."""
    normalized = unicodedata.normalize("NFD", text or "")
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn").casefold()


def contains_token(folded_text: str, token: str) -> bool:
    """Tim token nhu mot TU, khong phai mot doan giua tu.

    'hue' phai khop trong 'Hue' nhung KHONG khop trong 'hues'.
    """
    if not token:
        return False
    pattern = rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])"
    return re.search(pattern, folded_text) is not None


def destination_tokens(destination: Optional[str]) -> List[str]:
    """'Seoul, South Korea' -> ['seoul', 'south korea']."""
    if not destination:
        return []
    parts = [part.strip() for part in _SPLIT.split(destination) if part.strip()]
    tokens = [fold(part) for part in parts]
    return [token for token in tokens if len(token) >= 3]


def normalize_facts(facts) -> List[str]:
    """Nhan bat ky input nao tu LLM va tra ve list[string] sach.

    - string  -> [string]   (KHONG cat thanh tung ky tu)
    - dict    -> lay values
    - bo phan tu khong phai str, qua ngan (< 8 ky tu), qua dai (> 400 ky tu)
    - gop khoang trang, khu trung lap, gioi han so luong moi luot
    """
    if facts is None:
        return []
    if isinstance(facts, str):
        facts = [facts]
    elif isinstance(facts, dict):
        facts = list(facts.values())
    if not isinstance(facts, (list, tuple, set)):
        return []
    out: List[str] = []
    for raw in facts:
        if not isinstance(raw, str):
            continue
        text = " ".join(raw.split())
        if len(text) < MIN_FACT_CHARS or len(text) > MAX_FACT_CHARS:
            continue
        if text in out:
            continue
        out.append(text)
        if len(out) >= MAX_FACTS_PER_CALL:
            break
    return out


def mentions_destination(text: str, destination: Optional[str]) -> bool:
    folded = fold(text)
    return any(contains_token(folded, token) for token in destination_tokens(destination))


def fact_destination(text: str, destination: Optional[str]) -> Optional[str]:
    """Fact thuoc chuyen nao: co nhac ten diem den thi gan, khong thi de NULL (ben vung)."""
    return destination if mentions_destination(text, destination) else None


def fact_applies(
    text: str,
    destination: Optional[str],
    other_destinations: Iterable[str] = (),
) -> bool:
    """Fact nay con dung duoc cho chuyen hien tai khong.

    Khong biet diem den -> khong loc theo diem den, tranh loai oan.
    """
    cleaned = " ".join((text or "").split())
    # Phia DOC cung phai loai rac: ~110 dong 1 ky tu da nam san trong agent_facts tu
    # truoc, va nguoi dung khong cho phep xoa du lieu, nen chan tai day.
    if len(cleaned) < MIN_FACT_CHARS or len(cleaned) > MAX_FACT_CHARS:
        return False
    current = set(destination_tokens(destination))
    if not current:
        return True
    folded = fold(cleaned)
    if any(contains_token(folded, token) for token in current):
        return True
    for other in other_destinations or ():
        for token in destination_tokens(other):
            if token not in current and contains_token(folded, token):
                return False
    for city in KNOWN_DESTINATIONS:
        if city not in current and contains_token(folded, city):
            return False
    return True
