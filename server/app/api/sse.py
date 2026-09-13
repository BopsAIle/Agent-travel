"""Helper trinh bay cho tang API: dong goi su kien SSE va nhan trang thai node."""
import json

NODE_STATUS = {
    "en": {
        "planner": "Understanding your trip...",
        "flight_agent": "Searching flights...",
        "hotel_agent": "Searching hotels...",
        "event_agent": "Looking up events...",
        "aggregator": "Combining flight, hotel, and event results...",
        "activity_extractor": "Finding things to do...",
        "geocoding_agent": "Pinning places on the map...",
        "scheduler": "Building your day-by-day itinerary...",
        "evaluator": "Checking the plan against your budget...",
        "map_generator": "Drawing the trip map...",
        "report_formatter": "Writing your itinerary...",
        "place_lookup": "Looking up that place...",
        "lookup": "Looking up live results...",
        "quality_critic": "Checking the answer...",
    },
    "vi": {
        "planner": "Đang hiểu yêu cầu chuyến đi...",
        "flight_agent": "Đang tìm chuyến bay...",
        "hotel_agent": "Đang tìm khách sạn...",
        "event_agent": "Đang tìm sự kiện...",
        "aggregator": "Đang gộp kết quả máy bay, khách sạn và sự kiện...",
        "activity_extractor": "Đang tìm hoạt động...",
        "geocoding_agent": "Đang gắn địa điểm lên bản đồ...",
        "scheduler": "Đang xếp lịch từng ngày...",
        "evaluator": "Đang đối chiếu với ngân sách...",
        "map_generator": "Đang vẽ bản đồ chuyến đi...",
        "report_formatter": "Đang soạn lịch trình...",
        "place_lookup": "Đang tìm thông tin địa điểm...",
        "lookup": "Đang tìm kết quả thực tế...",
        "quality_critic": "Đang kiểm tra câu trả lời...",
    },
}


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def status_for_node(node_name: str, language: str) -> str:
    catalog = NODE_STATUS.get(language, NODE_STATUS["en"])
    if node_name in catalog:
        return catalog[node_name]
    fallback = NODE_STATUS["en"].get(node_name)
    if fallback:
        return fallback
    return f"Working on: {node_name.replace('_', ' ').title()}"
