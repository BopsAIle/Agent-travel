# Chẩn đoán 21/09/2026 — ảnh khách sạn không hiển thị trong report

**Triệu chứng:** mục "Thông tin khách sạn" hiện biểu tượng ảnh vỡ kèm alt text
`L'Escape, a Luxury Collection Hotel, Seoul Myeongdong`.

**Phiên bị lỗi:** `beb4e7b6-bb02-49eb-950d-dcbbcb7f9a10` — report ghi lúc `2026-09-21 16:11`,
3 đêm 25–28/09/2026, 3 người (2 người lớn + 1 trẻ em 5 tuổi).

**Nguồn đã kiểm chứng:** gọi lại RapidAPI `booking-com18` (`/stays/auto-complete`, `/stays/search`)
bằng đúng khoá trong `server/.env`; gọi thẳng CDN `cf.bstatic.com` cho từng URL; so sánh với
report của phiên trước đó (`dd5771b8…`, 16:02) và với `data/output/reports/*.md`.

---

## 0. Tổng hợp

| # | Mức | Vấn đề | Trạng thái |
| --- | --- | --- | --- |
| 1 | **P0** | `submit_result` bắt model **gõ lại** toàn bộ option, kể cả URL ảnh có chữ ký → chữ ký bị chép lệch → CDN trả **401** → ảnh vỡ | Đã sửa |
| 1b | P1 | Report đã lưu (`sessions.markdown_report`, `data/output/reports/*.md`) giữ nguyên URL hỏng nên hỏng mãi | Cần chạy lại lượt chat |
| 2 | **P1** | Không tầng nào kiểm chứng URL ảnh trước khi ghi vào report | Đã sửa |
| 3 | P2 | Trình duyệt hiện biểu tượng ảnh vỡ + alt text khi ảnh lỗi | Đã sửa |

---

## 1. Bằng chứng: chữ ký trong report không phải chữ ký của API

Cùng một ảnh `881342703`, cùng khách sạn, cùng ngày:

| Nguồn | `k=` trong URL | Gọi CDN |
| --- | --- | --- |
| report `dd5771b8…` (16:02) | `84df5b1e7c7b…e7ecfea27c6` | **HTTP 200** `image/jpeg` |
| report `beb4e7b6…` (16:11) — phiên bị lỗi | `84dfae0c8d7b…e7ecfea27c6` | **HTTP 401** `text/html` |
| API gọi lại lúc 16:23, `adults=3`, 25–28/09 | `84df5b1e7c7b…e7ecfea27c6` | **HTTP 200** |
| API gọi lại, `adults=2&children=5` (đúng tham số lượt 16:11) | `84df5b1e7c7b…e7ecfea27c6` | **HTTP 200** |

Hai chữ ký **giống nhau 56/64 ký tự cuối**, chỉ khác 8 ký tự đầu — dấu hiệu của việc chép tay
sai một đoạn, không phải chữ ký mới do API phát hành.

Các giả thuyết khác đã loại trừ bằng probe:

| Giả thuyết | Cách kiểm tra | Kết quả |
| --- | --- | --- |
| Khoá ký hết hạn theo thời gian | Gọi lại URL của report 16:02 sau 21 phút | Vẫn **200** → không phải hết hạn |
| Chữ ký gắn với tham số tìm kiếm | Gọi API với `adults=3` và `adults=2&children=5` | Trả **cùng** chữ ký |
| Đổi size làm hỏng chữ ký | Cùng ảnh, cùng `k`, đổi `square60` → `max500`/`max1024x768`/`max2000` | Tất cả **200** → chữ ký không phủ phần size |
| CDN chặn hotlink / chặn IP | Gọi `max500` không kèm `k`, và có `Referer: booking.com` | Có `k` hợp lệ: 200; thiếu `k`: 401 → CDN chỉ đòi chữ ký đúng |

Giá trong report 16:11 cũng trùng khớp API (`grossPrice = 800.9928` cho `adults=2&children=5`),
nên dữ liệu còn lại của lượt đó đúng; chỉ chữ ký ảnh bị lệch.

## 2. Cơ chế

`services/hotel-service` chạy tool loop rồi gọi `submit_result`, và `SubmitResultArgs.options`
buộc model **phát lại** danh sách option vào tham số tool call:

```
-> Tool loop step 1: search_hotels({"location_id": "eyJ…"})
-> Tool loop step 2: submit_result({"options": [{"hotel_name": "L'Escape…",
      "main_photo_url": "https://cf.bstatic.com/xdata/images/hotel/square60/881342703.jpg?k=84dfae0c…"}]})
```

`runner.py` lấy `payload["options"]` — tức **bản sao do model gõ** — làm kết quả cuối, thay vì
lấy danh sách thật mà tool vừa trả về. Chữ ký 64 ký tự hex là loại dữ liệu model dễ chép sai
nhất; sáu mươi ký tự sau đúng, tám ký tự đầu sai.

Đường đi tiếp theo: `AgentRunResponse.options` → `hotel_options`/`selected_hotel` của
orchestrator → `nodes/report.py` dựng `![tên](url)` → lưu vào `sessions.markdown_report`
(Postgres) và `data/output/reports/<session_id>.md` → client render lại bằng `react-markdown`.
Report **được lưu lại và hiển thị nhiều lần**, nên URL hỏng nằm trong đó thì hỏng mãi.

## 3. Rủi ro rộng hơn một tấm ảnh

Cùng đường đó, model còn phát lại mọi field khác của option: **giá**, **toạ độ** (activity/geocoding),
**flight number**, **url vé sự kiện**. Một chữ số giá bị chép lệch là sai ngân sách; một toạ độ lệch
là ghim bản đồ sai chỗ — khó phát hiện hơn nhiều so với một ảnh vỡ.

## 4. Hướng sửa (đã làm)

1. **`packages/agent_runtime/runner.py`: nguồn sự thật là tool output.** Model chỉ quyết định
   *chọn cái nào* (`selected_index`), không quyết định *nội dung* option.
   `_canonical_options` phân biệt hai kiểu agent:
   - **chép lại nguyên danh sách tool** (hotel/flight: chọn 1 trong N) → dùng bản gốc của tool,
     `selected_index` ánh xạ theo tên (khớp cả leg chuyến bay lồng nhau);
   - **lọc/curate danh sách tool** (event/activity: giữ 3–4 cái tốt nhất) → giữ nguyên danh sách
     model đã lọc, chỉ vá nội dung từng option bằng bản gốc.
   `submit_result` giờ chỉ cần `selected_index` + `reasoning` khi đã có tool trả danh sách.
2. **`app/domain/photos.py`: kiểm chứng URL trước khi ghi report.** `verified_photo_url` nâng size
   `square60`→`max500` và hỏi CDN bằng `HEAD`: **401/403/404/410 → bỏ ảnh**; probe không kết luận
   được (mạng lỗi, timeout, `HEAD` bị chặn, CDN 5xx) → **giữ ảnh**, không xoá ảnh tốt vì một lần probe hỏng.
3. **Client:** `MarkdownContent.jsx` render `img` qua component có `onError` — ảnh lỗi thì bỏ thẻ ảnh
   (không còn biểu tượng ảnh vỡ), phần chữ của khách sạn vẫn nguyên; thêm `loading="lazy"` và
   `referrerPolicy="no-referrer"`. `ReportDisplay` và `ChatWindow` dùng chung component này.
4. **`hotel-service/skills/SKILL.md` + mô tả tool `submit_result`:** nói rõ không chép lại option
   khi tool đã trả danh sách.

## 5. Test hồi quy

`server/tests/test_hotel_photo_url.py` — 22 test offline, dùng đúng cặp chữ ký thật
(`84df5b1e…` / `84dfae0c…`):

- chữ ký ảnh lấy từ tool output, không lấy bản model chép;
- lọc của event/activity không bị xoá, nhưng giá/chữ ký được vá từ tool;
- nhận diện chuyến bay qua `departure_leg` lồng nhau;
- 401/403/404/410 → bỏ ảnh; `None`/405/429/5xx → giữ ảnh;
- chạy thật `run_agent` với model giả: bản chép lệch **không** lọt ra `AgentRunResponse`
  (đã xác nhận test này fail nếu bỏ dòng `_canonical_options` trong `run_agent`).

Toàn bộ `server/tests`: **219 passed**.

## 6. Việc còn lại

- Report của phiên `beb4e7b6…` đã nằm trong Postgres (`sessions.markdown_report`) và trong
  `data/output/reports/beb4e7b6-bb02-49eb-950d-dcbbcb7f9a10.{md,html}` với chữ ký sai. Sửa code
  không vá được dữ liệu đã lưu: cần chạy lại lượt đó (refine/regenerate) để report mới được ghi.
- `agent_working` của hotel-service cũng giữ option cũ của phiên này; lượt refine kế tiếp sẽ lấy
  danh sách đó làm `existing_options`. Sau bản sửa này, option trả về app luôn là bản gốc của tool,
  nhưng dữ liệu cũ trong DB vẫn là bản chép lệch.
