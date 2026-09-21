"""Test hồi quy cho lỗi "không hiển thị được hình ảnh khách sạn" (21/09/2026).

Nguyên nhân đã kiểm chứng: `submit_result` bắt model **gõ lại** toàn bộ danh sách
option vào tham số tool call, kể cả URL ảnh Booking.com có chữ ký 64 ký tự hex.
Chuyến Seoul 16:11 ghi vào report chữ ký `84dfae0c…` trong khi API trả `84df5b1e…`
cùng ảnh, cùng ngày, cùng khách sạn → CDN trả HTTP 401 → report hiện ảnh vỡ.

Chạy offline: không gọi LLM, không ra mạng (mọi lần "hỏi CDN" đều qua probe giả).
"""
import sys
from pathlib import Path

import pytest

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.domain import photos  # noqa: E402
from app.domain.photos import normalize_photo_url, verified_photo_url  # noqa: E402
from app.schemas.trip import (  # noqa: E402
    Activity,
    DailyPlan,
    EvaluationResult,
    FlightInfo,
    FlightLeg,
    HotelInfo,
    Itinerary,
)
from packages.agent_runtime import runner  # noqa: E402

# Đúng cặp chữ ký của ảnh L'Escape (881342703) ngày 21/09/2026:
# bản API trả về (còn dùng được) và bản model chép lệch vào report (401).
GOOD_SIGNATURE = "84df5b1e7c7b9203a270304ac165f84cf2faeaf63026abdca9703e7ecfea27c6"
BAD_SIGNATURE = "84dfae0c8d7b9203a270304ac165f84cf2faeaf63026abdca9703e7ecfea27c6"

HOTEL_NAME = "L'Escape, a Luxury Collection Hotel, Seoul Myeongdong"


def photo_url(signature, size="square60", image="881342703"):
    return f"https://cf.bstatic.com/xdata/images/hotel/{size}/{image}.jpg?k={signature}&o="


def hotel_option(name, signature, price=800.99):
    return {
        "hotel_name": name,
        "price_per_night": round(price / 3, 2),
        "total_price": price,
        "rating": 9.3,
        "review_count": 2248,
        "rating_word": "Wonderful",
        "main_photo_url": photo_url(signature),
        "static_map_url": None,
    }


def executed_with(*outputs):
    """Transcript tool loop: các tool trả list, rồi submit_result của model."""
    entries = [
        {"name": "search_hotels", "args": {"location_id": "eyJ…"}, "output": output}
        for output in outputs
    ]
    entries.append({"name": "submit_result", "args": {}, "output": "Result recorded."})
    return entries


# ---------------------------------------------------------------------------
# 1 — Nguồn sự thật là tool output, không phải bản model chép lại
# ---------------------------------------------------------------------------

def test_chu_ky_anh_lay_tu_tool_output_khong_lay_ban_model_chep():
    trusted = [hotel_option(HOTEL_NAME, GOOD_SIGNATURE)]
    echoed = [hotel_option(HOTEL_NAME, BAD_SIGNATURE)]
    payload = {"options": echoed, "selected_index": 0, "reasoning": "r"}

    options, index = runner._canonical_options(payload, executed_with(trusted))

    assert options == trusted
    assert index == 0
    assert GOOD_SIGNATURE in options[0]["main_photo_url"]
    assert BAD_SIGNATURE not in options[0]["main_photo_url"]


def test_giu_dung_danh_sach_model_da_loc_nhung_va_noi_dung_tu_tool():
    """Event/activity lọc bớt danh sách tool — không được trả lại cả danh sách gốc."""
    trusted = [
        hotel_option("Josun Palace", BAD_SIGNATURE, price=4670.88),
        hotel_option(HOTEL_NAME, GOOD_SIGNATURE),
        hotel_option("Hotel28 Myeongdong", BAD_SIGNATURE, price=1550.48),
    ]
    # Model giữ 2 lựa chọn, và cả hai đều bị chép lệch chữ ký ảnh / giá.
    echoed = [
        hotel_option("Hotel28 Myeongdong", BAD_SIGNATURE, price=999.99),
        hotel_option(HOTEL_NAME, BAD_SIGNATURE),
    ]
    payload = {"options": echoed, "selected_index": 1}

    options, index = runner._canonical_options(payload, executed_with(trusted))

    # Công lọc của model được giữ nguyên (2 option, đúng thứ tự)...
    assert [item["hotel_name"] for item in options] == ["Hotel28 Myeongdong", HOTEL_NAME]
    # ...nhưng nội dung lấy từ tool: giá không bị model sửa, chữ ký ảnh đúng.
    assert options[0]["total_price"] == 1550.48
    assert GOOD_SIGNATURE in options[1]["main_photo_url"]
    assert index == 1


def test_nhan_dien_chuyen_bay_qua_leg_long_nhau():
    def flight(price, number):
        return {
            "price": price,
            "total_duration_minutes": 525,
            "departure_leg": {
                "airline": "VietJet Aviation",
                "flight_number": number,
                "departure_time": "11:15 PM",
            },
        }

    trusted = [flight(495.16, "VJ962"), flight(509.35, "VJ960")]
    echoed = [flight(1.0, "VJ962"), flight(2.0, "VJ960")]  # model chép lem gia
    payload = {"options": echoed, "selected_index": 1}

    options, index = runner._canonical_options(payload, executed_with(trusted))

    assert options == trusted
    assert options[index]["price"] == 509.35


def test_khong_nhan_dien_duoc_option_thi_giu_ban_cua_model():
    trusted = [{"total_price": 1.0}, {"total_price": 2.0}]
    echoed = [{"total_price": 1.0}, {"total_price": 9.0}]
    payload = {"options": echoed, "selected_index": 1}

    options, index = runner._canonical_options(payload, executed_with(trusted))

    assert options == echoed
    assert index == 1


def test_refine_khong_goi_tool_thi_giu_danh_sach_cua_model():
    existing = [hotel_option(HOTEL_NAME, GOOD_SIGNATURE)]
    payload = {"options": existing, "selected_index": 0}

    options, index = runner._canonical_options(payload, [])

    assert options == existing
    assert index == 0


def test_lan_goi_tool_cuoi_cung_la_nguon_option():
    first = [hotel_option("Hotel cu", BAD_SIGNATURE)]
    last = [hotel_option(HOTEL_NAME, GOOD_SIGNATURE)]

    options, _ = runner._canonical_options({"options": [], "selected_index": 0}, executed_with(first, last))

    assert options == last


def test_submit_result_khong_bi_coi_la_nguon_option():
    # submit_result trả chuỗi, không phải list → không được dùng làm option.
    executed = [
        {"name": "search_hotels", "args": {}, "output": [hotel_option(HOTEL_NAME, GOOD_SIGNATURE)]},
        {"name": "submit_result", "args": {}, "output": "Result recorded."},
    ]

    options, _ = runner._canonical_options({"options": [], "selected_index": 0}, executed)

    assert len(options) == 1
    assert GOOD_SIGNATURE in options[0]["main_photo_url"]


# ---------------------------------------------------------------------------
# 2 — Kiểm chứng URL ảnh trước khi ghi vào report
# ---------------------------------------------------------------------------

def test_nang_size_anh_nhung_giu_nguyen_chu_ky():
    assert normalize_photo_url(photo_url(GOOD_SIGNATURE, "square60")) == photo_url(
        GOOD_SIGNATURE, "max500"
    )
    assert normalize_photo_url(None) == ""
    assert normalize_photo_url(" none ") == ""


@pytest.mark.parametrize("status", [401, 403, 404, 410])
def test_bo_anh_khi_cdn_tu_choi_dut_khoat(status):
    assert verified_photo_url(photo_url(BAD_SIGNATURE), probe=lambda url, timeout: status) == ""


def test_giu_anh_khi_cdn_tra_200():
    kept = verified_photo_url(photo_url(GOOD_SIGNATURE), probe=lambda url, timeout: 200)
    assert kept == photo_url(GOOD_SIGNATURE, "max500")


@pytest.mark.parametrize("status", [None, 405, 429, 500, 503])
def test_khong_ket_luan_duoc_thi_giu_anh(status):
    """Mạng lỗi, timeout, HEAD bị chặn hay CDN hiccup đều KHÔNG phải bằng chứng URL hỏng."""
    assert verified_photo_url(photo_url(GOOD_SIGNATURE), probe=lambda url, timeout: status) != ""


# ---------------------------------------------------------------------------
# 3 — Report: ảnh được ghi bằng URL đã kiểm chứng
# ---------------------------------------------------------------------------

def _report_state(session_id):
    from app.domain.conversation import trip_request_from_slots

    plan = trip_request_from_slots(
        {
            "origin": "Hà Nội",
            "destination": "Seoul",
            "start_date": "2026-09-25",
            "end_date": "2026-09-28",
            "person": 3,
        }
    )
    leg = FlightLeg(
        departure_time="11:15 PM",
        arrival_time="05:30 AM",
        departure_airport="Noi Bai (HAN)",
        arrival_airport="Incheon (ICN)",
        duration_minutes=255,
        airline="VietJet",
        flight_number="VJ962",
        aircraft_type="",
    )
    flight = FlightInfo(price=495.16, departure_leg=leg, return_leg=leg, total_duration_minutes=525)
    hotel = HotelInfo(
        hotel_name=HOTEL_NAME,
        price_per_night=266.99,
        total_price=800.99,
        rating=9.3,
        review_count=2248,
        rating_word="Wonderful",
        main_photo_url=photo_url(BAD_SIGNATURE),
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
        "evaluation_result": EvaluationResult(action="APPROVE", feedback="ok", total_cost=1296.15),
    }


def test_report_bo_anh_khi_cdn_tu_choi(monkeypatch, tmp_path):
    import app.graph.nodes.report as report

    monkeypatch.setattr(report, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(photos, "_http_probe", lambda url, timeout: 401)

    session_id = "cccccccc-1111-2222-3333-444444444444"
    report.report_formattor_node(_report_state(session_id))
    text = (tmp_path / "reports" / f"{session_id}.md").read_text(encoding="utf-8")

    # Không còn dòng ảnh nào (bản "khách sạn khác" cũng không kèm ảnh)...
    assert "![" not in text
    # ...nhưng phần chữ của khách sạn vẫn nguyên.
    assert HOTEL_NAME in text
    assert "€800.99" in text


def test_report_ghi_anh_dung_chu_ky_api_tra(monkeypatch, tmp_path):
    import app.graph.nodes.report as report

    monkeypatch.setattr(report, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(photos, "_http_probe", lambda url, timeout: 200)

    session_id = "dddddddd-1111-2222-3333-444444444444"
    state = _report_state(session_id)
    state["final_itinerary"].selected_hotel.main_photo_url = photo_url(GOOD_SIGNATURE)
    report.report_formattor_node(state)
    text = (tmp_path / "reports" / f"{session_id}.md").read_text(encoding="utf-8")

    assert f"![{HOTEL_NAME}]({photo_url(GOOD_SIGNATURE, 'max500')})" in text
    assert BAD_SIGNATURE not in text


# ---------------------------------------------------------------------------
# 4 — Chạy thật `run_agent` với model giả: bản chép lệch không được lọt ra ngoài
# ---------------------------------------------------------------------------

class _FakeBoundModel:
    def __init__(self, replies):
        self._replies = list(replies)

    def invoke(self, messages):
        return self._replies.pop(0)


class _FakeModel:
    """Model gia: tra ve dung chuoi tool_call da dinh truoc."""

    def __init__(self, replies):
        self._replies = list(replies)

    def bind_tools(self, tools):
        return _FakeBoundModel(self._replies)


def _agent_request():
    from packages.agent_runtime.contract import AgentRunRequest, TripPayload

    return AgentRunRequest(
        user_id="2c76f49d-64ac-48db-8bc6-ad9a0bdeeed5",
        session_id="beb4e7b6-bb02-49eb-950d-dcbbcb7f9a10",
        task="search",
        trip=TripPayload(
            origin="Hà Nội",
            destination="Seoul",
            start_date="2026-09-25",
            end_date="2026-09-28",
            person=3,
        ),
    )


def _search_tool(trusted):
    from langchain_core.tools import StructuredTool

    def search_hotels(destination: str):
        return trusted

    return StructuredTool.from_function(
        func=search_hotels, name="search_hotels", description="search hotels"
    )


def _run_agent_with(trusted, submit_args, tmp_path):
    from langchain_core.messages import AIMessage

    replies = [
        AIMessage(
            content="",
            tool_calls=[{"name": "search_hotels", "args": {"destination": "Seoul"}, "id": "1"}],
        ),
        AIMessage(content="", tool_calls=[{"name": "submit_result", "args": submit_args, "id": "2"}]),
    ]
    return runner.run_agent(
        agent_id="hotel",
        skills_dir=tmp_path / "khong-co-skill",
        tools=[_search_tool(trusted)],
        request=_agent_request(),
        db=None,
        llm=_FakeModel(replies),
        fallback_prompt="test",
    )


def test_run_agent_tra_ve_option_that_khong_tra_ve_ban_chep_lem(tmp_path):
    trusted = [hotel_option(HOTEL_NAME, GOOD_SIGNATURE)]
    echoed = [hotel_option(HOTEL_NAME, BAD_SIGNATURE)]

    response = _run_agent_with(
        trusted,
        {"options": echoed, "selected_index": 0, "reasoning": "vi tri tot"},
        tmp_path,
    )

    assert BAD_SIGNATURE not in str(response.options)
    assert BAD_SIGNATURE not in str(response.selected)
    assert GOOD_SIGNATURE in response.options[0]["main_photo_url"]
    assert response.selected["hotel_name"] == HOTEL_NAME
    assert response.reasoning == "vi tri tot"


def test_run_agent_van_ton_trong_index_khi_model_khong_chep_option(tmp_path):
    trusted = [
        hotel_option("Josun Palace", BAD_SIGNATURE, price=4670.88),
        hotel_option(HOTEL_NAME, GOOD_SIGNATURE),
    ]

    response = _run_agent_with(trusted, {"selected_index": 1, "reasoning": "chon so 2"}, tmp_path)

    assert response.selected["hotel_name"] == HOTEL_NAME
    assert GOOD_SIGNATURE in response.selected["main_photo_url"]
