# Case khó 01 — "Refine" biến thành lập lại kế hoạch từ đầu, và trí nhớ chuyến đi rỗng

> Dùng file này theo 2 cách:
> - **Phần A** dán thẳng vào chat với AI của bạn (không kèm phần B/C).
> - **Phần C** là đáp án để bạn chấm điểm, **không đưa cho AI**.

---

## PHẦN A — Prompt dán cho AI

Bạn là kỹ sư backend của repo `AI-travel-agent` (FastAPI + LangGraph orchestrator trong `server/app/`, 5 microservice trong `server/services/`, React client trong `client/`). Đọc `README.md`, `docs/architecture.md` và code trước khi kết luận.

### Triệu chứng người dùng báo

Người dùng chat trên Web (endpoint `POST /chat-stream`):

1. Lượt 1: "Mình ở HCM, muốn đi Singapore 1–5/3/2026 cho 2 người, ngân sách 900 euro" → agent hỏi thêm → **kế hoạch chạy xong, itinerary + bản đồ hiển thị đầy đủ.**
2. Lượt 2 (cùng phiên): "Đổi giúp mình khách sạn rẻ hơn" → **agent chạy lại TOÀN BỘ pipeline từ đầu** (tìm chuyến bay, tìm khách sạn, tìm sự kiện, trích hoạt động, geocode, scheduler), dù chỉ đổi khách sạn. Mất thời gian gấp nhiều lần và đốt quota RapidAPI/Tavily.
3. Lượt 3: "Lần trước mình đi đâu ấy nhỉ?" → agent trả lời như **chưa từng có chuyến nào** (episodic memory rỗng/không có gì).
4. Mở lại chat từ sidebar (nút lịch sử): có tin nhắn, nhưng **không có itinerary, không có bản đồ** dù lượt 1 đã hiện đủ.
5. Xem `POST /chats/{id}`: `has_plan = false`, `trip_state = null`, `markdown_report` trống.

Nghi vấn ban đầu của team: "chắc là LangGraph không merge state, hoặc refine của evaluator bị off-by-one". **Cả hai đều không phải nguyên nhân.** Đừng sửa theo hai hướng đó nếu chưa chứng minh được.

### Việc bạn phải làm

1. **Tìm nguyên nhân gốc thật** và chứng minh bằng code path cụ thể (file + dòng), không phải bằng suy đoán. Nêu rõ **tại sao** triệu chứng 2, 3, 4 là **cùng một nguyên nhân**, không phải ba bug rời.
2. **Sửa** để:
   - Lượt refine giữ được state cũ: chỉ chạy lại đúng phần được yêu cầu (`refresh` hẹp), giữ `selected_flight`/`hotel_options`/`final_itinerary` cũ khi không đổi cấu trúc chuyến.
   - Sau khi graph chạy xong, `has_plan`, `trip_state`, `markdown_report` **được ghi xuống DB**, để lượt sau và `GET /chats/{id}` đọc đúng.
   - Episodic memory ghi ra summary **có nội dung chuyến đi thật** (khách sạn, chuyến bay, tổng chi phí), không phải bản rỗng.
   - Tin nhắn tổng kết cuối lượt cũng phải nằm trong lịch sử đã lưu.
3. **Viết test hồi quy offline** chứng minh lỗi đã chết.

### Ràng buộc (vi phạm là trượt)

- Test **không được** gọi LLM, **không được** cần Postgres, **không được** cần Docker. `pytest tests -q` phải pass toàn bộ, kể cả 6 file test hiện có.
- Giữ đúng luật kiến trúc trong `server/tests/test_structure.py`: phụ thuộc một chiều `api → graph → domain → core/db/memory → schemas`, mỗi node LangGraph một file riêng, chỉ `app/core/config.py` được đọc biến môi trường, không hardcode URL service.
- Giữ endpoint/SSE contract cho client: các event `session`, `slots`, `message`, `route`, `status`, `final_report` vẫn phải đúng thứ tự và đúng shape (client trong `client/src/services/` đang parse các event này).
- Không được "sửa" bằng cách bỏ tính năng: vẫn phải giữ được cả luồng full plan, luồng refine, và luồng lỗi provider (không có vé/khách sạn vẫn phải trả `issues` tử tế).
- Được phép sửa nhiều file. Không được đổi schema DB theo hướng phá dữ liệu đã có (được thêm cột, không được đổi nghĩa cột cũ).

### Định dạng câu trả lời mong muốn

1. **Chẩn đoán**: chuỗi nhân–quả, mỗi mắt xích kèm `file:line`. Nói rõ mắt xích nào bạn **đã chạy thử** và mắt xích nào chỉ suy luận từ code.
2. **Cách tái hiện tối thiểu** (không cần API key).
3. **Diff** đề xuất.
4. **Test hồi quy**: tên file, tên test, và giải thích test **sẽ fail** trên code cũ ở dòng nào.
5. **Rủi ro còn lại** và những chỗ bạn cố tình không sửa, kèm lý do.

Hãy tự kiểm tra: nếu giải pháp của bạn vẫn khiến lượt 2 chạy lại toàn bộ pipeline, bạn chưa xong.

---

## PHẦN B — Bẫy mồi (đừng đưa cho AI)

Ba "nghi phạm" trông rất giống bug nhưng không phải nguyên nhân. AI sa vào đây là dấu hiệu đọc code hời hợt:

1. `app/graph/nodes/evaluator.py:144-148` — `refinement_count` được tăng **trước** khi kiểm tra `count >= MAX_REFINEMENTS`, và bị tăng cả khi `APPROVE`. Trông như off-by-one, nhưng vòng lặp vẫn dừng đúng sau 2 lần refine. Không gây ra triệu chứng nào ở trên.
2. `app/graph/nodes/evaluator.py:138-171` — `should_refine_or_end` **mutate** `state['selected_hotel']` và không `return` gì khi `action` lạ. Là code xấu thật, nhưng không liên quan.
3. `app/graph/nodes/event.py:20` — `_should_skip_search(state, "event", state.get("events") is not None)` truyền `bool` thay vì list. Cũng là mùi code, không phải nguyên nhân.

Ngoài ra: `app/graph/nodes/scheduler.py:28-43` có nhánh "reuse existing daily plans". Trong luồng refine **thật**, nhánh này bị vô hiệu vì `build_graph_state` (`conversation.py:275-291`) đã xoá `final_itinerary` trước khi graph chạy — nên nó chỉ chạy trên giấy tờ. Nếu AI hí hoáy sửa nhánh này để "fix refine", nó đang sửa một nhánh không tới được.

---

## PHẦN C — Đáp án & thang điểm

### Nguyên nhân gốc (đã kiểm chứng)

*Cách kiểm chứng: chạy offline trên Python 3.10 với `server/` trên `sys.path` (không cần Postgres/LLM), gọi trực tiếp `determine_refresh`, `build_graph_state`, `_itinerary_digest` với `ChatSession` giả. Kết quả: `has_plan=False` → `refresh = ['flight','hotel','event','activities']` + `selected_flight=None`; `has_plan=True` → `refresh = ['flight','hotel']` + giữ `selected_flight`; digest trên state chưa persist → `"No itinerary has been generated yet."`. Bộ test hiện có: `133 passed in 7.26s`.*

**Working memory của lượt chat chưa bao giờ được ghi lại sau khi graph chạy xong.**

Chuỗi nhân–quả:

1. `chat_stream.py:61` — `get_or_create_session(...)` trả về **dataclass `ChatSession`** trong bộ nhớ (`app/domain/conversation.py:66-78`), không phải ORM row.
2. `chat_stream.py:69` → `run_supervised_turn` → `supervisor.py:106` `persist_working(db, session)` → `memory/manager.py:72` → `working.py:159 save_session`. **Đây là lần ghi DB duy nhất của lượt**, và nó xảy ra **trước** khi graph chạy.
3. `chat_stream.py:103-135` graph chạy xong, rồi code gán `session.trip_state = full_state` (dòng 111), `session.has_plan = ...` (112), `session.markdown_report` (113), và `session.messages.append(summary)` (124) — **tất cả chỉ nằm trong RAM**.
4. Lần ghi DB thứ hai (`chat_stream.py:137-141` → `after_plan_complete` → `supervisor.py:117-119`) **không phải chốt an toàn**: nó nằm trong `try` (không `finally`), chỉ chạy khi `result.should_plan` là true và không có exception nào ở giữa. Nhánh chat thường (`chat_stream.py:76-77 return`) và **mọi nhánh lỗi** thoát mà không ghi lại gì. `grep save_session` xác nhận toàn repo chỉ có hai điểm gọi: `memory/manager.py:73` và `memory/working.py:283` (`restore_session`).

   → Nguyên nhân gốc, phát biểu gọn: **working memory được persist ở thời điểm sai.** `run_supervised_turn` ghi session *trước* khi graph kịp sinh `final_itinerary`/`markdown_report`, và lần ghi sau graph là tuỳ nghi chứ không bắt buộc, nên state mới thường xuyên không bao giờ tới DB. Hệ quả:

5. **Triệu chứng 2 (refine thành replan)**: `chat_stream.py:79-85` gọi `determine_refresh(..., session.has_plan)` với `has_plan` đọc từ DB = `False` (giá trị cũ, chưa từng được ghi). `conversation.py:158-159`: `if not has_plan or intent == "plan": return list(ALL_REFRESH)` → trả `["flight","hotel","event","activities"]` cho **mọi** lượt refine. `build_graph_state` (`conversation.py:245-249`) thấy `set(refresh) >= set(ALL_REFRESH)` → `clear_search = True` → xoá sạch `selected_flight`, `hotel_options`, `final_itinerary`. Đúng bằng "chạy lại từ đầu".

   *Đã kiểm chứng offline*: với `has_plan=False` → `refresh = ['flight','hotel','event','activities']`, `selected_flight = None`; với `has_plan=True` → `refresh = ['flight','hotel']`, giữ nguyên `selected_flight`.

6. **Triệu chứng 3 (episodic rỗng)**: `memory/episodic.py:50` `if not session.has_plan: return None`; kể cả khi đọc được, `_episode_summary` (dòng 28-46) gọi `_itinerary_digest(session.trip_state)`. Với `trip_state` cũ/None, digest trả `"No itinerary has been generated yet."` → episode vô nghĩa. *Đã kiểm chứng offline*: digest trên state chưa persist = `No itinerary has been generated yet.`; trên state thật = `Current plan: Singapore from ... Hotel: Marina Bay (€400.0). Flight: ...`.

7. **Triệu chứng 4/5 (`GET /chats/{id}` trống)**: `chats.py:27` `load_session` → `_row_to_session` (`working.py:89-109`) đọc thẳng cột DB `has_plan`/`trip_state`/`markdown_report` — tất cả là giá trị cũ.

⇒ **Một nguyên nhân, bốn triệu chứng.** Sửa ở tầng ghi DB của working memory.

### Hướng sửa đúng (một cách)

- Trong `event_stream`, gom state cuối một cách chắc chắn (state trả về từ `astream` là **delta theo node**, không phải full state — hoặc dùng `travel_agent_app.aget_state(config)` sau khi stream xong), rồi cập nhật session.
- Chuyển `persist_working`/`save_session` cho lượt chat vào **`finally`** của `event_stream` (sau khi đã cập nhật `has_plan`, `trip_state`, `markdown_report`, `messages`), đảm bảo ghi được cả khi stream lỗi giữa chừng. `supervisor.py:106` có thể giữ (để lượt chat thường vẫn lưu slot) nhưng không được là lần ghi cuối.
- `after_plan_complete` phải chạy **sau** khi session mang state mới, và nên tách: ghi working trước, ghi episode sau.
- Cân nhắc: `full_state` dựng bằng `dict(initial_state)` + `update(chunk)` **không** phải state authoritative; `chunk` chỉ chứa key mà node trả về.

### Thang điểm (10)

| Điểm | Tiêu chí |
| --- | --- |
| 3 | Chẩn đoán đúng nguyên nhân gốc: working memory được ghi ở sai thời điểm — `supervisor.py:106` ghi **trước** graph, còn lần ghi sau graph (`supervisor.py:118` qua `chat_stream.py:137-141`) là tuỳ nghi, nằm trong `try` không `finally`, nên nhánh chat thường và mọi nhánh lỗi thoát mà không ghi. |
| 2 | Nối đúng **một** nguyên nhân → **cả bốn** triệu chứng, kèm `file:line` cho từng mắt xích (`determine_refresh` → `clear_search` → mất state; `upsert_episode` → digest rỗng; `load_session` → UI trống). |
| 2 | Sửa đúng chỗ, không sửa lan: lượt refine chỉ refresh phần cần, giữ state cũ; ghi DB trong `finally` (hoặc tương đương) nên cả nhánh lỗi và nhánh chat thường đều nhất quán. |
| 2 | Test hồi quy offline thật sự **fail trên code cũ** và pass sau khi sửa; `pytest tests -q` xanh toàn bộ, không cần LLM/Postgres. |
| 1 | Giữ đúng contract SSE + luật kiến trúc `test_structure.py`, không phá luồng lỗi provider. |
| −2 | Kết luận nguyên nhân là off-by-one của evaluator, hoặc đi sửa nhánh "reuse existing daily plans" trong `scheduler.py`, hoặc đổ lỗi cho LangGraph merge state mà không chứng minh. |

### Câu hỏi phụ để phân loại AI giỏi / AI trung bình

1. "Chứng minh `chunk` từ `astream` là delta, không phải full state — và chỉ ra chỗ nào trong repo đang dựa vào hiểu sai đó." (Trả lời đúng: `chat_stream.py:102-106` và `plan-trip-stream` phải tự merge delta để dựng `full_state`; `full_state` vì thế không phải state authoritative, và nếu một node không trả key nào thì dữ liệu cũ trong `full_state` bị giữ lại như thể còn đúng.)
2. "Nếu `persist_working` chuyển vào `finally`, điều gì xảy ra với lượt chat mà LLM hội thoại bị lỗi (`llm_failed`)?" (Trả lời đúng: `run_conversation_turn` vẫn tạo `ConversationTurn` rỗng và vẫn append message; session vẫn phải được ghi.)
3. "Vì sao `has_plan` không thể suy ra từ `session.trip_state.get('final_itinerary')` ở lượt sau, thay vì thêm cột?" (Trả lời đúng: hoàn toàn suy ra được — nhưng `trip_state` cũng chưa từng được ghi, nên phải sửa gốc trước; đây là test xem AI có hiểu vấn đề hay chỉ vá triệu chứng.)
