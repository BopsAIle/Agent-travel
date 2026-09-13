aggregator
    │
    ▼
activity_extractor     Tavily — lấy địa điểm vật lý
    │  (tên chỗ)
    ▼
geocoding_agent        Nominatim — gắn lat/lng
    │  (tọa độ)
    ▼
scheduler              xếp ngày + lắp Itinerary
    │  (cần đã có vé và KS)
    ▼
evaluator              Gemini so cost vs budget
    │
    ├── APPROVE / hết 2 vòng  →  map_generator  →  report_formatter  →  END
    └── REFINE_FLIGHT / REFINE_HOTEL  → quay lại đúng 1 worker (nét đứt cam)