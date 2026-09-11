# Giáo trình: Autonomous AI Travel Agent

Tài liệu này dùng để **dạy project** cho người mới: không giả định học viên đã biết LangGraph, microservices, hay SSE. Mục tiêu cuối khóa là học viên **chạy được hệ thống**, **vẽ được luồng một tin nhắn**, và **chỉ đúng file** khi được hỏi “chỗ này xảy ra ở đâu?”.

| File | Dùng khi nào |
| :--- | :--- |
| [instructor-notes.md](instructor-notes.md) | Người dạy chuẩn bị buổi học |
| [01-setup-and-tour.md](01-setup-and-tour.md) | Buổi 1 — chạy stack, tour sản phẩm |
| [02-frontend.md](02-frontend.md) | Buổi 2 — React chat UI |
| [03-orchestrator.md](03-orchestrator.md) | Buổi 3 — FastAPI, JWT, SSE, hội thoại |
| [04-langgraph.md](04-langgraph.md) | Buổi 4 — LangGraph + các node lập kế hoạch |
| [05-microservices.md](05-microservices.md) | Buổi 5 — 5 agent-service + tool loop |
| [06-memory.md](06-memory.md) | Buổi 6 — memory 3 tầng + pgvector |
| [07-devops.md](07-devops.md) | Buổi 7 — Docker, CI, OpenShift (tùy chọn) |
| [student-todos.md](student-todos.md) | Checklist to-do cho học viên (in / tick từng mục) |

Nếu chỉ có thời gian ngắn: làm buổi 1 → 3 → 4. Các buổi còn lại là “đi sâu”.

---

## Đối tượng

**Phù hợp nếu học viên đã:**

- Viết được Python cơ bản (hàm, class, `if`/`for`, đọc file).
- Biết HTTP là request/response (GET/POST, JSON).
- Từng thấy React hoặc HTML/JS (không cần giỏi).

**Chưa cần biết trước:** FastAPI, LangChain, LangGraph, Docker Compose, JWT, PostgreSQL, Kubernetes.

**Không phù hợp làm buổi đầu tiên nếu:** học viên chưa từng viết code. Hãy cho họ 1–2 buổi Python + Git trước.

---

## Sản phẩm học viên cầm tay được

Sau khóa học, học viên giải thích được (bằng lời, không cần thuộc lòng API):

1. User gõ chat → React stream SSE → Orchestrator.
2. Supervisor đọc memory, điền slot, quyết định có chạy planner hay chưa.
3. LangGraph chạy song song flight / hotel / event, rồi activity → geocode → lịch → đánh giá → báo cáo.
4. Mỗi microservice có LLM + tools + `SKILL.md`, không phải “một hàm search cứng”.
5. Postgres giữ user, chat, profile, embedding, telemetry.

---

## Lộ trình đề xuất (8 buổi × 2.5 giờ)

```
Buổi 1  Bản đồ hệ thống + chạy Docker + đi một chuyến thử
Buổi 2  Frontend: login, sidebar, SSE, AgentMonitor
Buổi 3  Orchestrator: auth, /chat-stream, supervisor, slots
Buổi 4  LangGraph: TripState, song song, evaluator loop
Buổi 5  Microservices: /agent/run, tools, RapidAPI/Tavily
Buổi 6  Memory: working / semantic / episodic + pgvector
Buổi 7  DevOps: Compose, metrics, CI (OpenShift nếu còn giờ)
Buổi 8  Tổng kết: vẽ lại kiến trúc từ nhớ + mini challenge
```

**Phiên bản 4 buổi (rút gọn):** 1, 3, 4, 5. Bỏ sâu frontend/DevOps; chỉ demo UI.

**Phiên bản 12 buổi:** tách buổi 3 thành API + conversation; tách buổi 5 thành 1 service/buổi; thêm buổi debug log + buổi viết test.

---

## Quy tắc dạy (áp dụng mọi buổi)

1. **Luôn bắt đầu từ hành vi user**, rồi mới mở code. Không dump 20 file lúc đầu.
2. **Một buổi = một câu hỏi lớn.** Ví dụ buổi 4: “Khi nào hệ thống bắt đầu search vé máy bay?”
3. **Học viên phải tự tick to-do** trong [student-todos.md](student-todos.md). Người dạy không làm hộ bước đọc file.
4. **Không bắt học viên nhớ tên API bên ngoài.** Chỉ cần biết Flight gọi Booking.com qua RapidAPI, Event gọi Ticketmaster, Activity gọi Tavily.
5. **Chi phí API:** mỗi lần plan trip tốn tiền OpenAI/Gemini + RapidAPI. Buổi demo dùng **một** query cố định; buổi sau reuse session đã có plan.

---

## Câu hỏi kiểm tra nhanh (dùng bất kỳ lúc nào)

Học viên đạt “hiểu project” nếu trả lời được 8/10:

- [ ] App chạy ở port nào? API ở port nào?
- [ ] JWT được lưu ở đâu trên trình duyệt?
- [ ] `/chat-stream` khác `/plan-trip-stream` chỗ nào?
- [ ] Slot nào bắt buộc trước khi planner chạy?
- [ ] Node nào chạy song song sau `planner`?
- [ ] Evaluator fail thì graph đi đâu?
- [ ] Flight service nhận request hình gì (`AgentRunRequest`)?
- [ ] Working memory khác semantic memory chỗ nào?
- [ ] Embedding dùng để làm gì?
- [ ] Prometheus lấy metrics từ endpoint nào?

Đáp án nằm rải trong các file buổi học; đáp án gộp ở cuối [instructor-notes.md](instructor-notes.md).
