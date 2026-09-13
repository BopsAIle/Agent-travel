"""Smoke test cho graph đã compile: node và cạnh phải đúng như thiết kế.

Nếu ai đó thêm/bớt node mà quên nối cạnh, test này gãy trước khi chạy thật.
"""
from app.graph.builder import app as travel_agent_app

NODE_MONG_DOI = {
    "planner",
    "flight_agent",
    "hotel_agent",
    "event_agent",
    "aggregator",
    "activity_extractor",
    "geocoding_agent",
    "scheduler",
    "evaluator",
    "map_generator",
    "report_formatter",
}

CANH_MONG_DOI = {
    ("__start__", "planner"),
    ("planner", "flight_agent"),
    ("planner", "hotel_agent"),
    ("planner", "event_agent"),
    ("flight_agent", "aggregator"),
    ("hotel_agent", "aggregator"),
    ("event_agent", "aggregator"),
    ("aggregator", "activity_extractor"),
    ("activity_extractor", "geocoding_agent"),
    ("geocoding_agent", "scheduler"),
    ("scheduler", "evaluator"),
    ("evaluator", "map_generator"),
    ("evaluator", "flight_agent"),
    ("evaluator", "hotel_agent"),
    ("map_generator", "report_formatter"),
    ("report_formatter", "__end__"),
}


def _graph():
    return travel_agent_app.get_graph()


def test_du_node():
    thuc_te = set(_graph().nodes) - {"__start__", "__end__"}
    assert thuc_te == NODE_MONG_DOI


def test_du_canh():
    thuc_te = {(e.source, e.target) for e in _graph().edges}
    assert thuc_te == CANH_MONG_DOI


def test_evaluator_re_nhanh_theo_dieu_kien():
    nhanh = {e.target: e.data for e in _graph().edges if e.source == "evaluator"}
    assert nhanh == {
        "map_generator": "end",
        "flight_agent": "refine_flight",
        "hotel_agent": "refine_hotel",
    }
