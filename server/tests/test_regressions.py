"""Test hồi quy cho 8 vấn đề trong docs/diagnostics/2026-09-21-seoul-plan-failure.md.

Chạy hoàn toàn offline: không gọi LLM, không cần Postgres, không cần Docker, không ra mạng.
Mỗi nhóm test khoá lại một lỗi đã xảy ra thật, để nó không quay lại.
"""
import importlib.util
import re
import sys
from pathlib import Path

import pytest

SERVER_ROOT = Path(__file__).resolve().parents[1]
SERVICE_ROOT = SERVER_ROOT / "services"
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.domain.money import (  # noqa: E402
    budget_label,
    detect_currency,
    normalize_trip_budget,
    parse_amount,
    to_eur,
)
from app.domain.planning_issues import (  # noqa: E402
    classify_provider_error,
    issue_message,
)
from app.schemas.trip import MIN_PROVIDER_CHILD_AGE, TripRequest  # noqa: E402
from packages.agent_runtime.facts import (  # noqa: E402
    fact_applies,
    fact_destination,
    normalize_facts,
)

# Đúng token thật mà Booking.com trả cho Seoul (envelope base64).
SEOUL_TOKEN = (
    "eyJjaXR5X25hbWUiOiJTZW91bCIsImNvdW50cnkiOiJTb3V0aCBLb3JlYSIsImRlc3RfaWQiOiItNzE2NTgzIiwiZGVzdF90eXBlIjoiY2l0eSJ9"
)
# Đúng fact đã làm nhiễu kế hoạch Seoul (viết trong chuyến London).
LONDON_FACT = "Ưu tiên khách sạn gần trung tâm London có điểm đánh giá từ 8.0 trở lên."
DURABLE_FACT = "Prefers direct flights when available."
# Đúng rác đã sinh ra ngày 20/09: mỗi ký tự là một dòng.
JUNK_ROWS = ["g", "i", "n", "ô", "ể", ",", "ế", "à"]


def _slots(**overrides):
    slots = {
        "origin": "Hà Nội",
        "destination": "Seoul",
        "start_date": "2026-09-25",
        "end_date": "2026-09-28",
        "person": 3,
    }
    slots.update(overrides)
    return slots


def _plan(**overrides):
    from app.domain.conversation import trip_request_from_slots

    return trip_request_from_slots(_slots(**overrides))


def _load_service_module(unique_name: str, service: str, filename: str = "main.py"):
    """Nạp một module của service, không để lẫn `search`/`schemas` giữa hai service."""
    pytest.importorskip("fastapi")
    pytest.importorskip("langchain_core")
    service_dir = SERVICE_ROOT / service
    saved = {name: sys.modules.pop(name) for name in ("search", "schemas") if name in sys.modules}
    sys.path.insert(0, str(service_dir))
    try:
        spec = importlib.util.spec_from_file_location(unique_name, service_dir / filename)
        module = importlib.util.module_from_spec(spec)
        sys.modules[unique_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(service_dir))
        for name in ("search", "schemas"):
            sys.modules.pop(name, None)
        sys.modules.update(saved)


# ---------------------------------------------------------------------------
# Vấn đề 1 — hợp đồng tool khách sạn: token base64, không phải dest_id
# ---------------------------------------------------------------------------

def test_dest_id_of_doc_dung_envelope_base64():
    main = _load_service_module("hotel_service_main", "hotel-service")
    assert main.dest_id_of(SEOUL_TOKEN) == "-716583"


def test_dest_id_of_khong_tu_bien_gia_tri_khac():
    main = _load_service_module("hotel_service_main", "hotel-service")
    # Không được ánh xạ một dest_id thành chính nó, cũng không được crash.
    assert main.dest_id_of("-716583") == ""
    assert main.dest_id_of("garbage") == ""
    assert main.dest_id_of("") == ""


def test_loi_guard_khach_san_khong_bi_goi_la_loi_nha_cung_cap():
    guard = (
        "location_id_not_from_lookup: Pass the exact opaque location token "
        "returned by lookup_location_id."
    )
    reason = classify_provider_error(guard)
    assert reason == "location_id_not_from_lookup"
    english = issue_message("hotel", reason, "en")
    vietnamese = issue_message("hotel", reason, "vi")
    # Phải nói rõ là CHƯA gọi được nhà cung cấp, và không được đổ lỗi cho họ.
    assert "before contacting" in english.lower()
    assert "chưa gọi được" in vietnamese
    assert "rejected" not in english.lower()
    assert "từ chối" not in vietnamese
    # Và phải khác hẳn thông báo của lỗi provider thật.
    assert english != issue_message("hotel", "provider_bad_request", "en")
    # Lỗi 400 thật của nhà cung cấp vẫn giữ nguyên cách phân loại cũ.
    assert classify_provider_error("provider_bad_request: rejected") == "provider_bad_request"
    assert classify_provider_error("provider_rate_limited: quota") == "provider_rate_limited"


# ---------------------------------------------------------------------------
# Vấn đề 3 — fact rác 1 ký tự và fact của chuyến khác
# ---------------------------------------------------------------------------

def test_string_tra_ve_mot_fact_chu_khong_bi_cat_thanh_tung_ky_tu():
    text = "Quan tâm ẩm thực Trung Quốc và các địa điểm nhạc sống khi lập lịch."
    assert len(list(text)) > 50  # đúng cái bẫy cũ: list(string) = từng ký tự
    assert normalize_facts(text) == [text]


def test_normalize_facts_bo_rac_va_gioi_han():
    assert normalize_facts(["", "   ", "ok", "g", ",", "ể", LONDON_FACT]) == [LONDON_FACT]
    assert normalize_facts({"a": DURABLE_FACT}) == [DURABLE_FACT]
    assert normalize_facts(None) == []
    assert len(normalize_facts([DURABLE_FACT + str(i) for i in range(20)])) == 5


def test_rac_1_ky_tu_trong_db_cu_khong_con_duoc_nap_vao_prompt():
    # Người dùng không cho xoá dữ liệu, nên phải chặn ở phía ĐỌC.
    kept = [row for row in JUNK_ROWS if fact_applies(row, "Seoul")]
    assert kept == []


def test_fact_cua_chuyen_london_khong_lot_vao_chuyen_seoul():
    assert fact_applies(LONDON_FACT, "Seoul") is False
    assert fact_applies(LONDON_FACT, "Seoul, South Korea") is False
    # Nhưng vẫn dùng được cho chính chuyến London.
    assert fact_applies(LONDON_FACT, "London") is True


def test_fact_ben_vung_van_dung_cho_moi_chuyen():
    assert fact_applies(DURABLE_FACT, "Seoul") is True
    assert fact_applies("allergic to peanuts", "Seoul") is True


def test_khop_theo_ranh_gioi_tu():
    # 'hue' không được khớp bên trong 'hues'...
    assert fact_applies("Prefers warm hues in photos.", "Seoul") is True
    # ...nhưng phải khớp đúng tên thành phố Huế.
    assert fact_applies("Muốn ghé Huế.", "Seoul") is False


def test_khong_biet_diem_den_thi_khong_loc_oan():
    assert fact_applies(LONDON_FACT, None) is True


def test_fact_destination_gan_dung_chuyen():
    assert fact_destination(LONDON_FACT, "London") == "London"
    assert fact_destination(LONDON_FACT, "Seoul") is None
    assert fact_destination(DURABLE_FACT, "Seoul") is None


# ---------------------------------------------------------------------------
# Vấn đề 5 — quy đổi ngân sách sang EUR
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("Ngân sách: 30.000.000 VND", "VND"),
        ("khoảng 2000 USD cho 3 người", "USD"),
        ("$1500", "USD"),
        ("ngân sách 900 euro", "EUR"),
        ("1.500.000đ", "VND"),
        ("500 won", "KRW"),
    ],
)
def test_detect_currency(text, expected):
    assert detect_currency(text) == expected


def test_dong_y_khong_bi_nham_thanh_tien_dong():
    assert detect_currency("đồng ý, đi 3 ngày") is None
    assert detect_currency("budget 2000") is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("30.000.000", 30000000.0),
        ("30,000,000", 30000000.0),
        ("1.5", 1.5),
        ("1,500", 1500.0),
        ("1,234.5", 1234.5),
        ("2 triệu", 2000000.0),
        ("500k", 500000.0),
        ("1.5tr", 1500000.0),
    ],
)
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


def test_ngan_sach_vnd_duoc_quy_doi_qua_duong_that():
    plan = _plan(budget=30000000, budget_currency="VND")
    assert plan.budget == round(to_eur(30000000, "VND"), 2)
    assert plan.budget == 1052.63
    assert plan.budget_original == 30000000
    assert plan.budget_currency == "VND"
    assert "30,000,000 VND" in budget_label(plan)


def test_quy_doi_idempotent_khong_chia_hai_lan():
    plan = _plan(budget=30000000, budget_currency="VND")
    once = plan.budget
    assert normalize_trip_budget(plan).budget == once
    assert normalize_trip_budget(plan, source_text="30.000.000 VND").budget == once


def test_khong_ro_tien_te_thi_giu_nguyen_hanh_vi_cu():
    assert _plan(budget=1200).budget == 1200
    assert _plan(budget=1200).budget_original is None


def test_so_sanh_ngan_sach_theo_eur_moi_co_nghia():
    """Trước đây 514 EUR bị so với 30.000.000 nên luôn 'trong ngân sách'."""
    plan = _plan(budget=30000000, budget_currency="VND")
    assert 514.13 < plan.budget  # 514 EUR < 1052 EUR: so sánh giờ có nghĩa


def test_moi_cho_tao_trip_request_deu_quy_doi_ngan_sach():
    """Bất biến: quy đổi nằm ở 2 chỗ tạo plan, không nằm trong schema.

    Thêm chỗ thứ ba mà quên gọi normalize_trip_budget thì test này fail.
    Lưu ý: phải loại `PartialTripRequest(` — chuỗi đó CHỨA `TripRequest(`.
    """
    calls_trip_request = re.compile(r"(?<![A-Za-z])TripRequest\(")
    app_root = SERVER_ROOT / "app"
    offenders = []
    for path in sorted(app_root.rglob("*.py")):
        if "__pycache__" in path.parts or path.name == "trip.py":
            continue
        source = path.read_text(encoding="utf-8")
        if calls_trip_request.search(source) and "normalize_trip_budget" not in source:
            offenders.append(path.relative_to(SERVER_ROOT).as_posix())
    assert not offenders, f"Tạo TripRequest mà không quy đổi ngân sách: {offenders}"


# ---------------------------------------------------------------------------
# Vấn đề 6 — trẻ em: không bao giờ bịa tuổi
# ---------------------------------------------------------------------------

def test_tre_em_chua_co_tuoi_thi_khong_gui_len_nha_cung_cap():
    plan = _plan(person=3, children=1)
    assert plan.provider_child_ages == []
    assert plan.adults == 3
    assert plan.children_charged_as_adults is True


def test_tre_em_du_tuoi_thi_gui_dung_so_nguoi_lon():
    plan = _plan(person=3, children=2, child_ages=[5, 7])
    assert plan.provider_child_ages == [5, 7]
    assert plan.adults == 1
    assert plan.children_charged_as_adults is False


def test_tuoi_duoi_nguong_khong_bao_gio_gui_len():
    """Đã đo thật: children=1 làm chuyến bay trả 0 kết quả."""
    assert MIN_PROVIDER_CHILD_AGE >= 2
    plan = _plan(person=2, children=1, child_ages=[1])
    assert plan.provider_child_ages == []
    assert plan.adults == 2


def test_thieu_tuoi_thi_khong_gui_du_da_biet_mot_be():
    plan = _plan(person=4, children=2, child_ages=[5])
    assert plan.provider_child_ages == []
    assert plan.adults == 4


@pytest.mark.parametrize(
    "service,filename",
    [("hotel-service", "main.py"), ("flight-service", "search.py")],
)
def test_adults_for_tru_tre_em_khoi_tong_so_khach(service, filename):
    module = _load_service_module(f"{service.replace('-', '_')}_adults", service, filename)
    assert module._adults_for(3, [5]) == 2
    assert module._adults_for(3, [5, 7]) == 1
    assert module._adults_for(3, None) == 3
    assert module._adults_for(1, [5, 7]) == 1  # không bao giờ còn 0 người lớn


def test_so_tre_em_khong_bi_roi_tu_luot_chat_toi_ke_hoach():
    """Đường thật của chat: ConversationTurn -> PartialTripRequest -> slots -> TripRequest.

    Đã xảy ra thật: thiếu field ở PartialTripRequest/slots_snapshot nên số trẻ em rơi
    mất trước khi tới kế hoạch, và report không có ghi chú nào.
    """
    from app.domain.conversation import (
        merge_slots,
        slots_snapshot,
        trip_request_from_slots,
    )
    from app.schemas.chat import ConversationTurn

    turn = ConversationTurn(
        reply="ok",
        detected_language="vi",
        intent="chat",
        origin="Hà Nội",
        destination="Seoul",
        start_date="2026-09-25",
        end_date="2026-09-28",
        person=3,
        children=1,
        budget=30000000,
        budget_currency="VND",
    )
    extracted = turn.to_extracted()
    assert extracted.children == 1, "số trẻ em rơi mất ở PartialTripRequest"

    slots = merge_slots({}, extracted)
    snapshot = slots_snapshot(slots)
    assert snapshot["children"] == 1, "số trẻ em rơi mất ở slots"

    plan = trip_request_from_slots(snapshot)
    assert plan.children == 1
    assert plan.children_charged_as_adults is True
    assert plan.budget == 1052.63


# ---------------------------------------------------------------------------
# Vấn đề 7 — report theo từng phiên
# ---------------------------------------------------------------------------

def test_report_stem_chong_path_traversal():
    pytest.importorskip("folium")
    pytest.importorskip("markdown2")
    from app.graph.nodes.report import _report_stem

    assert _report_stem({"session_id": "../../etc/passwd"}) == "etcpasswd"
    assert _report_stem({"session_id": ""}) == "unsessioned"
    assert _report_stem({}) == "unsessioned"
    assert _report_stem({"telemetry_run_id": "run-1"}) == "run-1"


def test_moi_phien_ghi_report_rieng_va_ban_moi_nhat_la_phien_cuoi(tmp_path, monkeypatch):
    pytest.importorskip("folium")
    pytest.importorskip("markdown2")
    from app.schemas import (
        Activity,
        DailyPlan,
        EvaluationResult,
        FlightInfo,
        FlightLeg,
        HotelInfo,
        Itinerary,
    )
    import app.graph.nodes.report as report

    monkeypatch.setattr(report, "OUTPUT_DIR", str(tmp_path))

    leg = FlightLeg(
        departure_time="01:40 AM",
        arrival_time="07:55 AM",
        departure_airport="Noi Bai (HAN)",
        arrival_airport="Incheon (ICN)",
        duration_minutes=255,
        airline="VietJet",
        flight_number="VJ960",
        aircraft_type="",
    )
    flight = FlightInfo(price=514.13, departure_leg=leg, return_leg=leg, total_duration_minutes=525)
    hotel = HotelInfo(
        hotel_name="Test Hotel",
        price_per_night=100.0,
        total_price=300.0,
        rating=8.5,
        review_count=10,
        rating_word="Great",
    )
    activity = Activity(
        name="Gwangjang Market",
        description="Cho truyen thong",
        location="Jongno-gu",
        time_of_day="Evening",
        latitude=37.57,
        longitude=127.0,
    )
    itinerary = Itinerary(
        selected_flight=flight,
        selected_hotel=hotel,
        daily_plans=[DailyPlan(day=1, activities=[activity])],
    )
    plan = _plan(budget=30000000, budget_currency="VND", children=1)
    session_a = "aaaaaaaa-1111-2222-3333-444444444444"
    session_b = "bbbbbbbb-9999-8888-7777-666666666666"

    def state_for(session_id):
        return {
            "session_id": session_id,
            "language": "vi",
            "trip_plan": plan,
            "final_itinerary": itinerary,
            "selected_flight": flight,
            "selected_hotel": hotel,
            "flight_options": [flight],
            "hotel_options": [hotel],
            "events": [],
            "extracted_activities": [activity],
            "refresh": [],
            "refinement_count": 0,
            "map_html": None,
            "memory_context": "",
            "evaluation_result": EvaluationResult(
                action="APPROVE", feedback="ok", total_cost=1200.0
            ),
        }

    report.report_formattor_node(state_for(session_a))
    report.report_formattor_node(state_for(session_b))

    report_a = tmp_path / "reports" / f"{session_a}.md"
    report_b = tmp_path / "reports" / f"{session_b}.md"
    assert report_a.exists() and report_b.exists()
    assert (tmp_path / "reports" / f"{session_a}.html").exists()
    # Bản "mới nhất" là phiên chạy sau, không ghi đè lên file của phiên trước.
    assert (tmp_path / "trip_itinerary.md").read_text(encoding="utf-8") == report_b.read_text(
        encoding="utf-8"
    )

    text = report_a.read_text(encoding="utf-8")
    # Ngân sách đã quy đổi và in kèm số gốc (vấn đề 5)...
    assert "30,000,000 VND" in text
    assert "€1,052.63" in text
    # ...và có ghi chú trẻ em chưa có tuổi (vấn đề 6).
    assert "chưa có tuổi" in text
