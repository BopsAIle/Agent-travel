# Chẩn đoán 21/09/2026 — chuyến Hà Nội → Seoul 25–28/09 không tạo được lịch trình

**Session phân tích:** `dfdcbe90-c516-4c48-b645-b1d19ae8a522` ("Hà Nội → Seoul", user `2c76f49d-64ac-48db-8bc6-ad9a0bdeeed5`, `has_plan = false`, cập nhật cuối `2026-09-21 07:30:53Z`).

**Nguồn đã kiểm chứng:** `docker logs` của 7 container travel + `travel-postgres`; truy vấn trực tiếp DB `travel_agent` (sessions / messages / user_facts / agent_facts / agent_working / agent_cache); probe trực tiếp Booking.com API **từ trong container `travel-hotel-service`**; `data/output/trip_itinerary.md`; đọc code trong `server/`.

**Lưu ý về dữ liệu:** 3 lượt cuối của session này nằm trong `messages` của Postgres. Thư mục `data/output/chats/` chỉ có 2 file từ 02–03/09 và **không có code nào ghi vào đó**, nên đó là dữ liệu mồ côi — xem mục 7.

> **Đính chính so với bản đầu của báo cáo.** Bản đầu kết luận `find_location_id()` "lấy nhầm field, phải decode base64 để lấy `dest_id`". **Sai, và hướng sửa đó sẽ làm lỗi thành 100%.** Probe thực tế cho thấy base64 `id` mới là giá trị `/stays/search` chấp nhận, còn `dest_id` bị trả HTTP 400. Mục 1 dưới đây là chẩn đoán đã kiểm chứng lại.

---

## 0. Tổng hợp

| # | Mức | Vấn đề | Trạng thái |
| --- | --- | --- | --- |
| 1 | **P0** | `lookup_location_id` trả token base64 opaque; model tự decode ra `dest_id` (giá trị API **từ chối**), guard nội bộ raise `provider_bad_request` → không có khách sạn → không có lịch trình | Đang xảy ra |
| 1b | **P0** | `hotel_agent` return sớm khi provider lỗi nên **fallback `/search` — đường đã probe ra HTTP 200 — không bao giờ chạy** | Đang xảy ra |
| 2 | **P0** | Geocoding: DNS `nominatim.openstreetmap.org` fail trong container + retry quá lâu → vượt timeout 120s → mọi toạ độ `null` | Đang xảy ra |
| 3 | **P1** | `agent_facts` bị nhiễm ~110 dòng rác 1 ký tự + fact của chuyến khác (London, "đi một mình") được nhét vào prompt Seoul | Dữ liệu rác vẫn đang được truy hồi |
| 4 | **P1** | Migration embedding `text-embedding-004` → `gemini-embedding-001` dở dang: script re-embed đã viết nhưng **chưa chạy**, 34 dòng thiếu vector, 11 file chưa commit | Đang dở dang |
| 5 | **P1** | Ngân sách 30.000.000 VND bị so trực tiếp với chi phí EUR → luôn "Within Budget" | Đang xảy ra |
| 6 | **P2** | `person=3` gửi thành `adults=3` cho cả hotel và flight → mất thông tin 1 trẻ em | Đang xảy ra |
| 7 | **P2** | Report ghi vào 1 file toàn cục `trip_itinerary.md` (không theo session); `data/output/chats/` mồ côi | Đang xảy ra |
| 8 | **P2** | `JWT_SECRET` mặc định 13 byte; `VITE_API_URL` cứng `localhost:5001`; chỉ 1/7 service được cấu hình `dns` | Đang xảy ra |

---

## 1. P0 — Vì sao nhánh khách sạn chết

### 1.1 Auto-complete trả hai field, chỉ một field dùng được

Probe từ trong container (`GET https://booking-com18.p.rapidapi.com/stays/auto-complete?query=Seoul`, HTTP 200), `data[0]`:

```json
{"latitude":37.561893,"country":"South Korea","label":"Seoul, South Korea","nr_hotels":5960,
 "dest_id":"-716583","dest_type":"city","city_name":"Seoul","name":"Seoul","hotels":5960,
 "id":"eyJjaXR5X25hbWUiOiJTZW91bCIsImNvdW50cnkiOiJTb3V0aCBLb3JlYSIsImRlc3RfaWQiOiItNzE2NTgzIiwiZGVzdF90eXBlIjoiY2l0eSJ9"}
```

`row["id"]` decode base64 ra chính envelope đó:

```json
{"city_name":"Seoul","country":"South Korea","dest_id":"-716583","dest_type":"city"}
```

Gọi `/stays/search` với cùng ngày `2026-09-25 → 2026-09-28`, `adults=3`, `currencyCode=EUR`:

| `locationId` truyền vào | Kết quả |
| --- | --- |
| `eyJjaXR5X25hbWUi...` (base64 `id`) | **HTTP 200** — trả về khách sạn thật (Josun Palace, Seoul Gangnam, …) |
| `-716583` (`dest_id`) | **HTTP 400** — `{"data":null,"errors":{"location":"Location is not available"},"status":false}` |

⇒ `find_location_id()` (`services/hotel-service/search.py:89-98`) trả `rows[0].get("id")` là **đúng**. Cache `agent_cache` cũng đang giữ giá trị đúng.

### 1.2 Mắt xích thật: model truyền `dest_id`, guard nội bộ chặn trước khi gọi API

Log đầy đủ của `travel-hotel-service` — dòng 7 và 11 dài **129 ký tự** và JSON **kết thúc trọn vẹn**; nếu là blob base64 thì dòng đã bị cắt ở 200 ký tự (do `_as_text(args)[:200]` tại `packages/agent_runtime/loop.py:68`):

```
-> Tool loop step 1: lookup_location_id({"city": "Seoul"})
--- Finding Location ID for Seoul ---
-> location id cache miss for Seoul, stored eyJjaXR5X25hbWUiOiJTZW91bCIsImNvdW50cnkiOiJTb3V0aCBLb3JlYSIsImRlc3RfaWQiOiItNzE2NTgzIiwiZGVzdF90eXBlIjoiY2l0eSJ9
-> Tool loop step 2: search_hotels({"location_id": "-716583", "start_date": "2026-09-25", "end_date": "2026-09-28", "person": 3})
-> Tool loop step 3: lookup_location_id({"city": "Seoul, South Korea"})
--- Finding Location ID for Seoul, South Korea ---
-> location id cache miss for Seoul, South Korea, stored eyJjaXR5X25hbWUiOiJTZW91bCIs...
-> Tool loop step 4: search_hotels({"location_id": "-716583", "start_date": "2026-09-25", "end_date": "2026-09-28", "person": 3})
-> Tool loop reached max_steps=4.
```

Model nhận tool output là chuỗi base64, **tự decode** (envelope bắt đầu bằng `eyJ` = `{"`), thấy field tên `dest_id` nên truyền `-716583` vào tham số có tên `location_id`. Đã kiểm tra DB: chuỗi `-716583` **không xuất hiện ở bất kỳ nguồn nào khác** (không có trong `messages`, `agent_facts`, `agent_cache`, `agent_working`) → decode base64 là nguồn duy nhất.

Guard tại `services/hotel-service/main.py:50-79`:

```python
def search_hotels(location_id, start_date, end_date, person):
    if location_id not in resolved_ids:            # resolved_ids chỉ chứa base64 id do lookup trả về
        raise HotelProviderError(
            "provider_bad_request",
            "location_id must come from lookup_location_id in this agent run.",
            status_code=400,
        )
    hotels = search_hotels_at(location_id, start_date, end_date, person)
```

`-716583` ∉ `resolved_ids` → **raise trước khi có bất kỳ HTTP call nào tới Booking.com**. Lỗi được trả về model dưới dạng tool output; model thử lại y hệt ở bước 3–4 (lần lookup thứ hai trả cùng blob nhưng dưới cache key khác) → hết 4 bước → không `submit_result` → `AgentRunResponse.options = []`, `errors = ["provider_bad_request: location_id must come from lookup_location_id in this agent run."]`.

### 1.3 Ba tầng biến một lỗi nhỏ thành lỗi chết

1. **Hợp đồng tool rò rỉ (leaky abstraction).** `lookup_location_id` trả về một token opaque 140 ký tự và không nói "hãy truyền lại nguyên văn". Tệ hơn, envelope chứa sẵn field **`dest_id`** — đúng cái tên mà tool sau đang cần (`location_id`) — nhưng chính giá trị đó lại bị API từ chối. Tool description chỉ nói "Booking.com location id from lookup_location_id", `SKILL.md` chỉ nói "Reuse the cached id when available".
2. **Guard kiểm tra nguồn gốc, không kiểm tra hình dạng.** Nó chỉ so `in resolved_ids`, nên chặn nhầm một giá trị "trông rất giống id", không đưa gợi ý sửa, và gán mã `provider_bad_request` — trùng mã với lỗi HTTP 400 thật của provider, khiến log/monitoring không phân biệt được "guard nội bộ chặn" với "provider từ chối".
3. **Không có đường lui.** `max_steps=4` (`loop.py:13`) trong khi hai lần lặp hoàn toàn giống nhau (không có tín hiệu mới để model sửa), và `hotel.py:76-83` **return sớm** khi `errors and not hotel_options` nên fallback `/search` không chạy. Trong khi `/search` (`services/hotel-service/main.py:118-127`) gọi `find_location_id()` → `search_hotels_at()` trực tiếp, tức **đúng tổ hợp vừa probe ra HTTP 200**. Fallback này chắc chắn chạy được và đã không được gọi.

Hệ quả phụ: thông báo cho người dùng sai hai lần. `classify_provider_error` (`app/domain/planning_issues.py:34-53`) thấy chuỗi `provider_bad_request` → `hotel:provider_bad_request` → *"Dịch vụ khách sạn từ chối địa điểm hoặc ngày tìm kiếm được gửi lên."* Thực tế provider chưa hề được gọi, và không ai từ chối địa điểm hay ngày cả.

### 1.4 Hệ quả cuối

`docker logs travel-orchestrator`:

```
--- Running Activity Scheduling Agent ---
-> Missing selected flight or hotel, skipping schedule generation.
--- Running Smart Evaluator Agent (High IQ Mode) ---
-> Plan is incomplete because required provider data is missing.
-> Markdown report saved to: output/trip_itinerary.md
```

`evaluator_agent` trả `INCOMPLETE` (`nodes/evaluator.py:20-29`) → `trip_itinerary.md` chỉ có header lỗi + 10 chuyến bay, và tin nhắn cuối trong chat là:

> Mình chưa tạo được lịch trình đầy đủ: — Dịch vụ khách sạn từ chối địa điểm hoặc ngày tìm kiếm được gửi lên.

Chuyến bay **thành công** (10 option, VietJet VJ960 €514.13) — vấn đề nằm hoàn toàn ở nhánh hotel.

### 1.5 Hướng sửa

1. **Sửa hợp đồng tool** (`services/hotel-service/main.py`): cho `lookup_location_id` trả về cấu trúc tự giải thích thay vì chuỗi trần, ví dụ `{"location_id": "<blob>", "name": "Seoul", "dest_type": "city"}`, kèm description nói rõ **truyền lại nguyên văn `location_id`**, và bổ sung cùng câu đó vào `SKILL.md`.
2. **Guard tự sửa lỗi**: nếu giá trị nhận được khớp `^\-?\d+$` (tức model đã dùng `dest_id`), thì hoặc ánh xạ sang blob đã resolve trong run, hoặc trả lỗi hành động được ("bạn vừa truyền `dest_id`; hãy truyền chuỗi `location_id` mà `lookup_location_id` trả về"). Tách mã lỗi riêng (ví dụ `location_id_not_from_lookup`) khỏi `provider_bad_request`.
3. **Cho provider error đi qua fallback**: bỏ return sớm ở `hotel.py:76-83`, chạy `/search` rồi mới kết luận `hotel_failure_reason` — đây là đường đã chứng minh chạy được.
4. **Dọn cache key**: `agent_cache` của hotel đang trộn hai thế hệ key — `new york`, `trùng khánh`, `chongqing, china` (không prefix) lẫn `booking18:location:<city>`. Thống nhất một format và xoá row cũ không còn đường đọc.
5. **KHÔNG** decode base64 để lấy `dest_id` — hướng đó chắc chắn HTTP 400.

---

## 2. P0 — Geocoding: DNS fail + retry vượt timeout

`docker logs travel-orchestrator`:

```
-> Geocoding /agent/run failed, fallback /geocode: HTTPConnectionPool(host='geocoding-service',
   port=8003): Read timed out. (read timeout=120)
```

`docker logs --timestamps travel-geocoding-service` (lúc 07:32, tức **sau** khi orchestrator đã bỏ cuộc lúc 07:30:52):

```
requests.exceptions.ConnectionError: HTTPSConnectionPool(host='nominatim.openstreetmap.org', port=443):
Max retries exceeded with url: /search?q=N+Seoul+Tower%2C+Yongsan-gu%2C+Seoul%2C+South+Korea...
(Caused by NameResolutionError(... Failed to resolve 'nominatim.openstreetmap.org'
([Errno -5] No address associated with hostname)))
...
-> Tool loop step 3: submit_result({"options": [{"name": "Myeongdong Shopping Street", ...
   "latitude": null, "longitude": null, ...}]})
```

Chuỗi vấn đề:

- Container **không resolve được** `nominatim.openstreetmap.org` (lúc thì `Errno -2`, lúc `Errno -5` = NXDOMAIN).
- geopy + `RateLimiter` retry rồi mới bỏ, nên 5 địa điểm mất **~7 phút** (07:25 → 07:32) — vượt xa timeout 120s của orchestrator (`nodes/geocoding.py:31-36`).
- Orchestrator bỏ cuộc → chạy fallback `/geocode` từng địa điểm (`geocoding.py:62-79`), nhưng fallback gọi cùng service đang hỏng DNS → cũng vô ích, chỉ tốn thêm timeout 30s/địa điểm.
- Kết quả: mọi `latitude/longitude` = `null` → không có bản đồ, và công việc của service bị đốt vô ích sau khi client đã ngắt.

**Bất đối xứng cấu hình đáng ngờ:** `docker-compose.yaml:46-48` chỉ cấp DNS tường minh cho **một** service:

```yaml
  server:
    dns:
      - 8.8.8.8
      - 8.8.4.4
```

5 service còn lại (kể cả `geocoding-service`) không có block `dns:` nào → dùng DNS nội bộ của Docker. Đây là dấu hiệu ai đó từng gặp lỗi DNS ở orchestrator và chỉ vá một chỗ.

**Hướng sửa:** thêm `dns:` cho cả 6 service; thêm geocoder dự phòng hoặc bảng toạ độ offline cho các điểm phổ biến; đặt **deadline tổng** cho node geocoding (ví dụ 20s) và cắt retry, thay vì để geopy retry mặc định; cache cả kết quả `null` để không lặp lại.

---

## 3. P1 — Memory bị nhiễm: fact rác + fact của chuyến khác

### 3.1 ~110 dòng `agent_facts` là 1 ký tự

`SELECT` trên `agent_facts`: **143 dòng, 132 dòng tạo ngày 20/09**, trong đó ~110 dòng có `text` dài đúng 1 ký tự:

```
activity | g | i | n | ô | t | n | ả | , | ế | à | n | v | c | i | g | u | ú | b | g | ố | n | h | n | v | p | à | o | ê | ...
```

Đường đi của lỗi (vẫn còn trong code hiện tại):

1. Model gọi `submit_result` với `facts_to_remember` là **string** thay vì list.
2. `_fallback_from_tools` (`packages/agent_runtime/runner.py:243-257`) đọc **args thô** của tool call — tức là **chưa qua validate pydantic** của `SubmitResultArgs` — rồi `list(facts_to_remember or [])` → **cắt string thành từng ký tự**.
3. `runner.py:209-211`: `extra_facts = payload.get("facts_to_remember")` → `memory.add_facts(user_id, extra_facts)`.
4. `DomainMemory.add_facts` (`packages/agent_runtime/memory.py:96-132`) không kiểm tra kiểu, không giới hạn độ dài/số lượng → insert từng ký tự, mỗi ký tự một row + một embedding.

Các ký tự bị xen kẽ nhau là do 4 agent (flight/hotel/event/activity) chạy song song trong cùng lượt và cùng ghi từng ký tự.

**Rác này vẫn đang được nhét vào prompt hôm nay** — `docker logs travel-orchestrator`:

```
-> Activity memory_hits: ['fact:Quan tâm ẩm thực Trung Quốc và các địa điểm nhạc sống khi lập lịch hoạt động.',
  ..., 'fact:ể', 'fact:,']
```

Tin tốt: fact ghi **hôm nay** (21/09) đã sạch (6 dòng, đủ 768 chiều) — dữ liệu rác là di sản từ 20/09, nhưng **code path gây ra nó chưa được chặn**.

### 3.2 Fact của chuyến khác lọt vào Seoul

`agent_facts` scope theo `(agent_id, user_id)` — **không theo chuyến/session** — và truy hồi top-5 theo cosine, không lọc tính liên quan. Với cùng user `2c76f49d`, các fact sau được nạp vào lượt Seoul (log orchestrator):

```
-> Event memory_hits: ['fact:Ưu tiên du lịch một mình.', 'fact:Quan tâm đến ẩm thực Trung Quốc.', ...]
-> Hotel memory_hits: ['fact:Ưu tiên khách sạn gần trung tâm London có điểm đánh giá từ 8.0 trở lên.']
```

Ba fact này **mâu thuẫn trực tiếp** với chuyến đang lập: đi 3 người (2 lớn + 1 trẻ em), ở **Seoul** chứ không phải London, ưu tiên mua sắm + Michelin chứ không phải ẩm thực Trung Quốc. Chúng đến từ các session trước cùng user: "Bangkok → London" (20/09), "Hà Nội → Hong Kong" (21/09).

Thêm một đường nhiễm nữa ở tầng profile: `apply_profile_updates` (`app/memory/semantic.py:88-94`) **union vĩnh viễn** `interests`:

```python
merged = list(dict.fromkeys([*existing, *[str(item) for item in value if item]]))
```

`user_profiles.interests` của user này hiện là `["ẩm thực Trung Quốc", "lịch sử", "kiến trúc", "ẩm thực địa phương", "nhạc sống", "sự kiện diễn ra trong thời gian chuyến đi", "mua sắm", "ẩm thực Michelin"]` — "ẩm thực Trung Quốc" từ chuyến Hong Kong sẽ dính mãi vào mọi chuyến sau.

### 3.3 Hướng sửa

- `add_facts` (cả 2 bản): chỉ nhận `list[str]`; bỏ qua phần tử không phải `str`, ngắn hơn ~10 ký tự, hoặc dài quá ~300 ký tự; giới hạn số fact mỗi lượt.
- `_fallback_from_tools`: chuẩn hoá `facts_to_remember` (`str` → `[str]`) trước khi trả về.
- Dọn dữ liệu: xoá row có `length(text) <= 3` trong `agent_facts`/`user_facts`.
- Thêm scope theo chuyến/destination cho fact (ví dụ cột `destination`/`trip_key`) hoặc TTL, để "khách sạn gần trung tâm London" không được nạp khi lập kế hoạch Seoul.
- `interests` nên là preference **có thể thay**, không union vĩnh viễn; hoặc tách "sở thích dài hạn" khỏi "sở thích chuyến này".

---

## 4. P1 — Migration embedding dở dang (11 file chưa commit)

Bối cảnh (theo ghi chú trong `app/core/config.py` và `embed.py`): `text-embedding-004` đã bị Google tắt 14/01/2026 → chuyển sang `gemini-embedding-001`, ép `output_dimensionality=768` cho khớp cột `Vector(768)` trong `app/db/models.py:12`.

Đã kiểm chứng:

- Image `ai-travel-agent-server` build lúc `2026-09-21 14:08 +07`, container chạy code mới: `output_dimensionality` **có** trong `/app/app/memory/embed.py`, `gemini-embedding-001` **có** trong `/app/app/core/config.py`.
- Fact ghi hôm nay có vector **768 chiều** → đường ghi mới hoạt động.

Vấn đề còn lại:

- **Script re-embed chưa từng chạy xong.** `server/scripts/reembed_memory.py` đã có (và đã nằm trong image) nhưng không có `data/output/reembed_failures.json`; và **34/142** dòng `agent_facts` vẫn `embedding IS NULL`, **3/4** dòng `user_facts` (memory semantic cấp du khách) **thiếu vector**. Nếu script đã chạy, các dòng này đã được lấp hoặc nằm trong báo cáo lỗi.
- Hệ quả: vector cũ (10–11/09, 20/09) và vector mới (21/09) **có thể nằm ở hai không gian vector khác nhau** trong cùng một cột, không có cột nào ghi lại model đã sinh vector. Đúng như docstring của chính script cảnh báo: *"so cosine với vector của gemini-embedding-001 là vô nghĩa… retrieve memory trả về thứ tự rác (mà vẫn trông như hợp lệ)"*.
- Với dòng thiếu embedding, `retrieve_facts` cho điểm `0.0` (`packages/agent_runtime/memory.py:84-86`) → gần như không bao giờ được chọn khi câu query có vector.
- 11 file đang sửa dở **chưa commit**: `packages/agent_runtime/embed.py` (+304 dòng), `app/memory/embed.py`, `app/memory/semantic.py`, `app/core/config.py`, `app/core/telemetry.py`, `README.md`, `client/src/components/AgentMonitor.jsx`, `docs/plans/...`, `server/.env.example`, `app/memory/episodic.py`, `packages/agent_runtime/memory.py`; thêm mới `server/scripts/reembed_memory.py`, `server/tests/test_embed_memory.py`.

**Hướng sửa:** chạy `docker exec -it travel-orchestrator python /app/scripts/reembed_memory.py --dry-run` rồi chạy thật; xem `reembed_failures.json`; thêm cột `embed_model` (được phép thêm cột) để lần sau biết vector nào cũ; commit khối việc này và chạy `pytest tests -q`.

---

## 5. P1 — Ngân sách 30.000.000 VND chưa từng được kiểm tra

`nodes/evaluator.py:31-35`:

```python
flight_and_hotel_cost = selected_flight.price + selected_hotel.total_price   # EUR
total_daily_spending = daily_spending * trip_plan.person * trip_plan.days
total_cost = flight_and_hotel_cost + total_daily_spending
budget = trip_plan.budget                                                     # 30000000 (VND)
```

`total_cost` tính bằng **EUR** vì cả flight-service (`currency_code: "EUR"`, `search.py:261`) lẫn hotel-service (`currencyCode: "EUR"`, `search.py:116`) đều trả EUR, còn `budget` lấy nguyên con số từ câu người dùng ("30.000.000 VND"). So sánh `total_cost > budget` → `514.13 > 30_000_000` luôn sai → **luôn "Within Budget"**, và `budget_label` (dòng 78) in ra `€30000000`.

Trong repo không có bước quy đổi tiền tệ nào. Vì vậy câu trong log flight agent — *"Phù hợp ưu tiên bay nhanh… và ngân sách 30.000.000 VND cho 3 người"* — là khẳng định **không có cơ sở kiểm chứng** (€514.13/người × 3 ≈ 1.542 EUR ≈ 44 triệu VND, đã vượt ngân sách, nhưng không tầng nào phát hiện).

**Hướng sửa:** chuẩn hoá tiền tệ ngay ở planner (lưu `budget_eur` + `budget_original` + `currency`), hoặc trả giá theo `VND` từ provider; hiển thị đúng đơn vị trong evaluator/report.

---

## 6. P2 — Mất thông tin trẻ em

Chuyến là **3 người: 2 người lớn + 1 trẻ em**, nhưng `TripPayload.person = 3` được gửi thẳng thành số người lớn:

- `services/hotel-service/search.py:114`: `"adults": str(person)`
- `services/flight-service/search.py:259`: `"adults": str(person)`

Không có trường `children`/`child_ages` ở `TripPayload` hay trong request của 2 service. Hệ quả: giá và sức chứa phòng/ghế đều tính như 3 người lớn — sai cho gia đình có trẻ em (nhiều khách sạn tính phụ phí trẻ, giường phụ; giá vé trẻ em khác người lớn).

**Hướng sửa:** thêm `adults` + `children` (kèm tuổi nếu có) vào `TripPayload` và vào request của service, map đúng vào tham số provider.

---

## 7. P2 — Report toàn cục, `chats/` mồ côi

`nodes/report.py:355-357` ghi **một** file cố định:

```python
md_path = os.path.join(OUTPUT_DIR, "trip_itinerary.md")
html_path = os.path.join(OUTPUT_DIR, "trip_itinerary.html")
```

`OUTPUT_DIR = "output"` (`app/core/config.py:58`) và compose mount `./data/output:/app/output`. Mọi session/user dùng chung 2 file này → chạy song song thì **ghi đè lẫn nhau**; mở lại chat cũ không biết report nào là của mình; không có `session_id` trong tên hay nội dung file. `sessions.has_plan` vẫn `false` dù file report đã được ghi.

`data/output/chats/*.json` (2 file 02–03/09) là **mồ côi**: không có code nào ghi vào thư mục này, cũng không có code đọc nó. Lịch sử chat thật nằm ở bảng `sessions`/`messages` trong Postgres.

**Hướng sửa:** ghi `output/reports/{session_id}.md|html` và lưu đường dẫn vào `sessions.markdown_report`; xoá hoặc migrate `data/output/chats/`.

---

## 8. P2 — Vận hành / cấu hình

- `docker-compose.yaml:43`: `JWT_SECRET: ${JWT_SECRET:-dev-change-me}` — khoá HMAC 13 byte. Log orchestrator lặp lại `InsecureKeyLengthWarning: The HMAC key is 13 bytes long, which is below the minimum recommended length of 32 bytes` mỗi lần decode token.
- `docker-compose.yaml:6`: `VITE_API_URL: "http://localhost:5001"` được **bake lúc build** → client chỉ gọi được API khi trình duyệt chạy trên chính máy host; mở từ máy khác là hỏng.
- 30 container khác trên máy đang `Exited` (milvus, agentic-customer-service, aibridge, ai_finance…) — không phải lỗi repo nhưng gây nhiễu log/tài nguyên khi debug.
- `GET /chats` trả 401 khi không có token — hành vi đúng theo `tests/test_api.py:57`, ghi lại đây chỉ để khỏi nhầm là bug.

---

## 9. Thứ tự sửa đề xuất

1. **Sửa hợp đồng tool `lookup_location_id` + guard tự sửa lỗi** (mục 1.1–1.2) — đây là mắt xích trực tiếp khiến không có lịch trình. Nhớ: **không** decode base64 sang `dest_id`.
2. **Bỏ return sớm trong `hotel_agent`**, cho provider/guard error đi qua fallback `/search` (mục 1.3) — đường này đã probe ra HTTP 200.
3. **Geocoding deadline + DNS cho mọi service** (mục 2) → có bản đồ, và không đốt 7 phút cho mỗi lượt.
4. **Chặn + dọn fact rác, scope fact theo chuyến** (mục 3) → chất lượng chọn khách sạn/hoạt động.
5. **Chạy re-embed + thêm cột model + commit khối việc dở** (mục 4) → memory ngữ nghĩa hoạt động thật.
6. **Chuẩn hoá tiền tệ** (mục 5) → ngân sách mới có ý nghĩa.
7. Trẻ em (6), report theo session (7), JWT/DNS/URL (8).

---

## 10. Trạng thái sau khi sửa — 21/09/2026

Cả 8 vấn đề đã sửa, có test hồi quy offline, và **đã xác minh bằng một chuyến Hà Nội → Seoul chạy thật qua API**.

| # | Cách sửa | Bằng chứng sống |
| --- | --- | --- |
| 1 | `lookup_location_id` nói rõ token là opaque; guard **tự dịch** `dest_id` → token; mã lỗi đổi thành `location_id_not_from_lookup`; `SKILL.md` + mô tả tool yêu cầu truyền nguyên văn | `search_hotels({"location_id": "eyJ…"})` → `Found 10 hotels` → `submit_result` (trước đây `-716583` → guard → chết sau 4 bước) |
| 1b | `hotel_agent` không `return` sớm nữa; lỗi đi qua fallback `/search` (trừ lỗi xác thực/hạn mức) | đường dự phòng giờ tới được |
| 2 | `dns: 8.8.8.8/8.8.4.4` cho **cả 8** service; node geocoding có ngân sách 20s + 10s; service tự bỏ cuộc sau 12s; geopy `max_retries=1`, `timeout=5` | 7/8 địa điểm có toạ độ, không còn timeout 120s |
| 3 | `normalize_facts` chặn rác ở đường **ghi**; `fact_applies` chặn ở đường **đọc**; cột `destination` + `KNOWN_DESTINATIONS` | `memory_hits` sạch, `stored 2 fact(s) for destination='Seoul'` |
| 4 | Cột `embed_model` cho 3 bảng, ghi khi lưu; `apply_light_migrations` tự `ALTER … IF NOT EXISTS` khi khởi động; README có SQL đếm dòng cũ | cột tự xuất hiện sau `up -d`, không cần SQL tay |
| 5 | `app/domain/money.py` + bảng tỷ giá trong `config.py`; `budget` = EUR, giữ `budget_original`/`budget_currency` | report: `€1,052.63 (from 30,000,000 VND)` và `vượt ngân sách €57.79` |
| 6 | `adults`/`children`/`child_ages` đi tới **cả hai** service; **không bao giờ bịa tuổi** (tuổi 1 làm chuyến bay trả 0 kết quả); report ghi chú khi tạm tính trẻ như người lớn | `slots có children: [1]`, report có dòng "1 trẻ em chưa có tuổi…" |
| 7 | `reports/<session_id>.md|.html`, giữ bản "mới nhất"; `_report_stem` chặn path traversal | report riêng theo từng phiên |
| 8 | Bỏ `JWT_SECRET` khỏi `environment:` (nó **đè** `env_file:`); khoá 64 byte trong `server/.env`; cảnh báo khi còn dùng khoá dev; README nói rõ `VITE_API_URL` nhúng lúc build | khởi động không còn `InsecureKeyLengthWarning` |

Test: `195 passed` trong `server/tests/` (gồm `test_structure.py` về luật kiến trúc và `test_regressions.py` cho 8 vấn đề).

### Chưa làm, có lý do

- **Re-embed chưa chạy** (chưa được cho phép) → memory ngữ nghĩa vẫn lùi về "lấy mới nhất" cho tới khi chạy hai lệnh trong README.
- **Chưa xoá fact rác** trong `agent_facts` (chưa được cho phép) → đã chặn ở phía đọc nên không còn lọt vào prompt.
- **Chưa commit** (chưa được cho phép).

### Rủi ro còn lại phát hiện trong lúc sửa

- `requirements.txt` để `folium` **không ghim phiên bản**. Lần build này kéo về bản mà `import folium` không tự nạp `folium.plugins`, làm graph chết ở Map Generator (`module 'folium' has no attribute 'plugins'`) và **không lưu được kế hoạch**. Đã sửa bằng `import folium.plugins` (bền với mọi phiên bản), nhưng nên ghim phiên bản để tránh lặp lại.
- `gemini-2.5-flash` đã bị Google khai tử (`404 NOT_FOUND`, gợi ý `models/gemini-3.6-flash`) → evaluator luôn rơi vào nhánh "approved due to evaluator error". Cần đổi `GEMINI_MODEL`.
- Lỗi guard nội bộ và lỗi nhà cung cấp giờ đã tách mã, nhưng **`provider_bad_request` vẫn có thể do cả hai nguồn** nếu nhà cung cấp trả 400 thật.

