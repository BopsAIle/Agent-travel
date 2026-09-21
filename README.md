# AI Travel Agent

![React](https://img.shields.io/badge/React-20232A?style=for-the-badge&logo=react&logoColor=61DAFB)
![Vite](https://img.shields.io/badge/Vite-646CFF?style=for-the-badge&logo=vite&logoColor=white)
![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)
![LangGraph](https://img.shields.io/badge/LangGraph-E10098?style=for-the-badge&logo=langchain&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![OpenShift](https://img.shields.io/badge/Red%20Hat%20OpenShift-EE0000?style=for-the-badge&logo=redhatopenshift&logoColor=white)

Chat agent lập lịch trình du lịch: hiểu tiếng tự nhiên (tiếng Việt / English), nhớ sở thích người dùng qua nhiều phiên, rồi điều phối 5 microservice để tìm chuyến bay, khách sạn, sự kiện, hoạt động và vẽ bản đồ.

Người dùng chat. **Supervisor** phân loại ý định. Nếu đủ thông tin chuyến đi, **LangGraph** chạy pipeline song song, đánh giá ngân sách, rồi stream lịch trình về UI qua SSE.

---



## Hệ thống gồm những gì

Chạy local bằng Docker Compose: **8 container** trên một bridge network.


| Thành phần                                        | Vai trò                                                                               |
| ------------------------------------------------- | ------------------------------------------------------------------------------------- |
| **Frontend**                                      | React 19 + Vite, production serve bằng Nginx. Chat, lịch sử, stream tiến trình agent. |
| **Orchestrator**                                  | FastAPI + LangGraph. Auth JWT, hội thoại, memory, pipeline lập kế hoạch.              |
| **PostgreSQL 16 + pgvector**                      | User, session, tin nhắn, profile, embedding memory, telemetry.                        |
| **Flight / Hotel / Event / Activity / Geocoding** | FastAPI độc lập. Mỗi service có skill riêng và vòng lặp tool (`POST /agent/run`).     |


Prometheus + Grafana nằm ở layer OpenShift, không đi kèm `docker-compose.yaml`.

---



## Luồng hội thoại

Supervisor không luôn chạy planner. Mỗi tin nhắn đi một trong các nhánh:

1. **Chat / slot-fill** — hỏi thêm điểm đi, điểm đến, ngày, số người.
2. **Lookup** — chỉ tìm vé, khách sạn, sự kiện hoặc hoạt động (không lập lịch đầy đủ).
3. **Place lookup** — giải thích một địa điểm trong lịch trình đã có, có quality critic (Gemini).
4. **Full plan** — đủ slot thì chạy LangGraph và trả itinerary + bản đồ.

Memory được đọc trước lượt chat, rồi ghi lại sau lượt: profile bền vững, fact embedding, và episode của chuyến đã xong.

```
Tin nhắn
    │
    ▼
[Supervisor]  đọc memory → chat / slot-fill → gate địa điểm & lookup
    │
    ├── chat          → trả lời, hỏi thêm
    ├── lookup        → gọi microservice /search
    ├── place_lookup  → chi tiết địa điểm + critic
    └── plan          → LangGraph pipeline
```

---



## Pipeline lập kế hoạch

```
[Planner]  parse điểm đến, ngày, ngân sách, số người
    │
    ├── [Flight Agent] ──┐
    ├── [Hotel Agent]  ──┤  song song
    └── [Event Agent]  ──┘
            │
            ▼
      [Aggregator]
            │
            ▼
 [Activity Extractor]  Tavily / activity-service
            │
            ▼
  [Geocoding Agent]    Nominatim
            │
            ▼
      [Scheduler]      lịch từng ngày
            │
            ▼
  [Evaluator]  Gemini đối chiếu ngân sách
    ├── PASS  → bản đồ Folium → báo cáo Markdown
    └── FAIL  → refine flight hoặc hotel, rồi chạy lại
```

Flight / hotel / activity agent gọi `POST /agent/run` trên service tương ứng. Service load `skills/SKILL.md`, gọi tool (Booking.com, Tavily, …), rồi `submit_result` — không bịa giá.

---



## Kiến trúc

```mermaid
flowchart TD
    User((User)) -->|HTTP + SSE| FE["Frontend<br/>React 19 + Nginx"]
    FE -->|/chat-stream| Orch["Orchestrator<br/>FastAPI + LangGraph"]
    Orch <-->|SQL + pgvector| DB[("PostgreSQL 16")]

    subgraph Internal["Internal network"]
        Flight["Flight :8000"]
        Hotel["Hotel :8001"]
        Activity["Activity :8002"]
        Geo["Geocoding :8003"]
        Evt["Event :8004"]
    end

    Orch -->|"REST /agent/run và /search"| Flight
    Orch -->|REST| Hotel
    Orch -->|REST| Activity
    Orch -->|REST| Geo
    Orch -->|REST| Evt

    subgraph External["External APIs"]
        Booking["Booking.com / RapidAPI"]
        TM["Ticketmaster"]
        Tavily["Tavily"]
        OSM["OpenStreetMap"]
        LLM["OpenAI / Groq / Gemini"]
    end

    Flight --> Booking
    Hotel --> Booking
    Evt --> TM
    Activity --> Tavily
    Geo --> OSM
    Orch --> LLM
```



Trên OpenShift, Prometheus scrape `/metrics` của orchestrator và các service; Grafana đọc Prometheus.

---



## Cấu trúc thư mục

```
AI-travel-agent/
├── client/                     React 19 + Vite
│   └── src/
│       ├── components/         Component + CSS riêng của nó
│       ├── context/            AuthContext
│       ├── services/           api.js, chatHistory.js
│       └── styles/             CSS toàn cục
│
├── server/
│   ├── app/                    Orchestrator
│   │   ├── main.py             Tạo FastAPI app, gắn router
│   │   ├── api/                Tầng HTTP: auth, chats, metrics, chat_stream, sse
│   │   ├── core/               config, llm, security, telemetry, metrics, quality
│   │   ├── graph/              builder (LangGraph), state, supervisor
│   │   │   └── nodes/          Mỗi node một file + common.py
│   │   ├── domain/             conversation, lookup, places, place_lookup, reply_format
│   │   ├── memory/             working / episodic / semantic + embed
│   │   ├── db/                 SQLAlchemy base, models, session
│   │   └── schemas/            trip, chat, auth, memory
│   ├── packages/agent_runtime/ Runtime dùng chung cho 5 microservice
│   ├── services/               flight, hotel, activity, geocoding, event
│   ├── scripts/                check_apis.py
│   └── tests/                  Smoke test cấu trúc, graph, API
│
├── deploy/
│   ├── openshift/              Manifest
│   └── scripts/                deploy_all.sh, update_service.sh
├── docs/                       architecture.md, plans/
└── data/output/                File sinh ra lúc chạy (không commit)
```

**Chiều phụ thuộc** trong `server/app/`, một chiều và có test khoá lại:

```
api → graph → domain → core / db / memory → schemas
```

`api/` chỉ nhận request và trả SSE; `graph/` điều phối các node; `domain/` là logic
hội thoại và tra cứu; `core/` là hạ tầng dùng chung. Tầng dưới không được import
tầng trên — `tests/test_structure.py` kiểm tra điều này, cùng với quy tắc chỉ
`core/config.py` được đọc biến môi trường.

### Chạy test

```bash
cd server
pip install -r requirements.txt -r requirements-dev.txt
pytest tests -q
```

Test không cần Postgres và không gọi LLM.

---


## Tính năng

**Hội thoại**

- Chat đa lượt, sidebar lịch sử, SSE stream từng bước agent (song ngữ EN/VI).
- Supervisor giữ slot chuyến đi và chỉ kích hoạt planner khi đủ origin, destination, ngày, số người.
- Lookup nhanh (vé / khách sạn / sự kiện / hoạt động) mà không cần lập full itinerary.

**Memory ba tầng (orchestrator)**

- **Working** — slot, tin nhắn, trạng thái phiên.
- **Episodic** — chuyến đã đi, embedding, retrieve theo similarity.
- **Semantic** — profile bền (`UserProfile` + `UserFact`): thành phố nhà, ngân sách, diet, kiểu khách sạn, nhịp đi. Không lưu ngày/giá của chuyến hiện tại.

**Agent-service**

- Runtime chung `packages/agent_runtime`: tool loop, skill file, domain memory, cache (ví dụ IATA).
- Mỗi service có `SKILL.md` mô tả cách chọn option và fact được phép ghi.

**Độ tin cậy**

- Evaluator (Gemini) phản biện ngân sách rồi refine có mục tiêu.
- Quality gate lọc câu trả lời lặp / thoái hóa.
- Retry + timeout với API ngoài; service phụ lỗi thì vẫn trả được phần còn lại.
- Nội dung option không đi qua bản sao của model: `submit_result` chỉ chọn `selected_index`,
  runtime lấy danh sách thật từ tool output — chữ ký URL ảnh Booking.com từng bị chép lệch
  nên CDN trả 401 ([chẩn đoán](docs/diagnostics/2026-09-21-hotel-photo-broken.md)).
  Ảnh khách sạn còn được kiểm chứng (`HEAD`) trước khi ghi vào report, và client bỏ thẻ ảnh
  nếu ảnh vẫn lỗi.

**Bảo mật & quan sát**

- Đăng ký / đăng nhập JWT (`PyJWT` + `bcrypt`). Dữ liệu chat và memory theo từng user.
- Container non-root, arbitrary UID (OpenShift).
- Prometheus instrumentator trên FastAPI; run/span agent lưu PostgreSQL.

---



## Tech stack


| Nhóm     | Công cụ                                                 | Dùng để                      |
| -------- | ------------------------------------------------------- | ---------------------------- |
| Frontend | React 19, Vite 7, Nginx                                 | SPA, serve production        |
|          | `@microsoft/fetch-event-source`                         | SSE                          |
|          | `react-markdown`, `remark-gfm`                          | Render itinerary             |
| AI       | LangGraph, LangChain                                    | DAG đa agent, tool calling   |
|          | OpenAI (`OPENAI_MODEL`, mặc định `gpt-5.6-luna`)        | Planner, supervisor, chat    |
|          | Groq (nếu có `GROQ_API_KEY`)                            | LLM trong agent-service      |
|          | Gemini                                                  | Evaluator + place critic     |
| Backend  | FastAPI, Uvicorn, Pydantic                              | API và schema                |
|          | Folium, Geopy                                           | Bản đồ và geocode            |
| DB       | PostgreSQL 16 + pgvector, SQLAlchemy 2                  | Persistence + vector search  |
| Auth     | PyJWT, bcrypt                                           | JWT                          |
| Data     | Booking.com (RapidAPI), Ticketmaster, Tavily, Nominatim | Vé, KS, sự kiện, POI, tọa độ |
| Infra    | Docker Compose                                          | Dev local                    |
|          | OpenShift / Kubernetes                                  | Deploy                       |
| CI       | GitHub Actions                                          | Build & push image           |


---



## Chạy local

**Cần sẵn:** Docker Desktop, và API key: OpenAI (hoặc Groq cho agent-service), Gemini, Tavily, RapidAPI (Booking.com), Ticketmaster.

### 1. Clone và cấu hình

```bash
git clone https://github.com/your-username/AI-travel-agent
cd AI-travel-agent
cp server/.env.example server/.env
```

Điền `server/.env`:

```bash
OPENAI_API_KEY=your_openai_key
OPENAI_MODEL=gpt-5.6-luna
OPENAI_REASONING_EFFORT=low

# Tùy chọn: agent-service dùng Groq thay vì OpenAI
GROQ_API_KEY=
GROQ_MODEL=llama-3.3-70b-versatile

GEMINI_API_KEY=your_gemini_key
# Embedding cho memory; mặc định đã đúng, chỉ khai báo khi muốn đổi model.
# GEMINI_EMBED_DIM phải khớp EMBEDDING_DIM trong server/app/db/models.py.
GEMINI_EMBED_MODEL=models/gemini-embedding-001
GEMINI_EMBED_DIM=768
TAVILY_API_KEY=your_tavily_key
RAPIDAPI_KEY=your_rapidapi_key
TICKETMASTER_API_KEY=your_ticketmaster_key

# Compose ghi đè host thành postgres; bản local thuần dùng localhost
DATABASE_URL=postgresql://travel:travel@localhost:5432/travel_agent
JWT_SECRET=change-me-in-production
JWT_EXPIRE_HOURS=72
```



### 2. Docker Compose

```bash
docker-compose up --build
```


| Service          | URL                                                          |
| ---------------- | ------------------------------------------------------------ |
| Web              | [http://localhost:3000](http://localhost:3000)               |
| API orchestrator | [http://localhost:5001](http://localhost:5001)               |
| Health           | [http://localhost:5001/health](http://localhost:5001/health) |


Đợi log orchestrator `Uvicorn running on http://0.0.0.0:8000`, rồi mở [http://localhost:3000](http://localhost:3000).

Kiểm tra API upstream (chạy từ máy host; script tự exec vào container nếu DNS Docker không resolve):

```bash
python server/scripts/check_apis.py
python server/scripts/check_apis.py --quick
```

### Frontend gọi API ở đâu

`VITE_API_URL` được **nhúng lúc build** (Vite bake biến môi trường vào bundle), không đọc lúc chạy:

```yaml
# docker-compose.yaml, service client
build:
  args:
    VITE_API_URL: "http://localhost:5001"
```

Nên client chỉ gọi được API khi trình duyệt chạy trên **chính máy host**. Mở web từ máy khác thì phải sửa giá trị rồi build lại (`docker compose build client`). Muốn dùng được từ mọi máy thì cho nginx của client proxy `/api` sang `server:8000` — nhớ `proxy_buffering off` cho SSE của `/chat-stream`.

### Đổi model embedding

Memory lưu vector trong pgvector nên đổi model là đổi luôn không gian vector. `text-embedding-004` đã bị Google tắt ngày 14/01/2026, mặc định hiện tại là `gemini-embedding-001` (ép 768 chiều bằng `output_dimensionality`, khớp `EMBEDDING_DIM` trong `server/app/db/models.py`).

Khi đổi `GEMINI_EMBED_MODEL`, phải re-embed dữ liệu cũ, nếu không memory ngữ nghĩa sẽ trả về thứ tự rác:

```bash
docker exec -it travel-orchestrator python /app/scripts/reembed_memory.py --dry-run
docker exec -it travel-orchestrator python /app/scripts/reembed_memory.py
```

Script idempotent (chạy lại chỉ tính lại embedding). Mặc định gộp 100 text/request — mức tối đa API cho phép — nên 1000 dòng cũng chỉ tốn ~10 request.

Từ nay mỗi dòng memory có cột `embed_model` ghi lại **model đã sinh vector cho dòng đó**. Dòng cũ (tạo trước khi có cột) để `NULL`, nghĩa là **chưa rõ model** và phải coi như có thể cũ. `--dry-run` in ra số dòng thuộc model khác. Kiểm tra trực tiếp:

```sql
SELECT 'agent_facts' AS bang,
       count(*) FILTER (WHERE embed_model IS NULL) AS chua_ro,
       count(*) FILTER (WHERE embed_model IS NOT NULL
                          AND embed_model <> 'models/gemini-embedding-001') AS khac_model
FROM agent_facts
UNION ALL SELECT 'user_facts',
       count(*) FILTER (WHERE embed_model IS NULL),
       count(*) FILTER (WHERE embed_model IS NOT NULL
                          AND embed_model <> 'models/gemini-embedding-001') FROM user_facts
UNION ALL SELECT 'episodes',
       count(*) FILTER (WHERE embed_model IS NULL),
       count(*) FILTER (WHERE embed_model IS NOT NULL
                          AND embed_model <> 'models/gemini-embedding-001') FROM episodes;
```

Nếu truy vấn trên còn đếm ra dòng nào thì **phải chạy lệnh re-embed thật** (bỏ `--dry-run`); để nguyên thì memory ngữ nghĩa vẫn so cosine giữa hai không gian vector khác nhau và xếp hạng sai — mà vẫn trông như hợp lệ.

**Quota**: Gemini free tier cho **100 request/phút** cho mỗi model embedding (429 `RESOURCE_EXHAUSTED`, quotaId `...EmbedContentRequestsPerMinutePerUserPerProjectPerModel`). Script chờ đúng `retryDelay` mà API trả về (thường ~45s) rồi làm tiếp, không bỏ dở. Nếu còn dòng lỗi, script in lý do từng nhóm kèm số ký tự và ví dụ text, đồng thời ghi `data/output/reembed_failures.json`:

```bash
# chỉ chạy lại một bảng
docker exec -it travel-orchestrator python /app/scripts/reembed_memory.py --table agent_facts
# giãn nhịp khi ứng dụng đang chạy song song và cùng ăn quota
docker exec -it travel-orchestrator python /app/scripts/reembed_memory.py --sleep 10
```

Trong lúc chat thì ngược lại: gặp 429 **không** chờ 45s (sẽ treo câu trả lời), embedding của lượt đó bị bỏ và memory lùi về fallback "lấy mới nhất". Text dài hơn 6000 ký tự bị cắt trước khi embed để không rơi vào giới hạn 2048 token của model.

Trên OpenShift thay bằng `oc exec deploy/travel-orchestrator -- python /app/scripts/reembed_memory.py`.

---



### File kết quả trong `data/output`

| Đường dẫn | Nội dung |
| --- | --- |
| `reports/<session_id>.md` · `.html` | Report của **từng phiên chat** — mở lại chat cũ vẫn tra được đúng report của mình |
| `trip_itinerary.md` · `.html` | Bản **mới nhất**, tiện mở nhanh khi debug; nhiều phiên chạy song song thì file này bị ghi đè |
| `reembed_failures.json` | Chỉ có khi script re-embed gặp dòng lỗi |
| `chats/*.json` | **Dữ liệu mồ côi**: không còn code nào ghi hay đọc thư mục này. Lịch sử chat thật nằm ở bảng `sessions` / `messages` trong Postgres. Xoá được. |

## Deploy OpenShift

Manifest nằm trong `deploy/openshift/`. Script `deploy/scripts/deploy_all.sh` build image, push Docker Hub, tạo Secret/PVC, apply YAML, gắn frontend vào Route backend.

```bash
oc login -u developer -p developer https://api.crc.testing:6443
chmod +x deploy/scripts/deploy_all.sh
./deploy/scripts/deploy_all.sh
```


| File                             | Nội dung                                              |
| -------------------------------- | ----------------------------------------------------- |
| `deploy/openshift/microservices/*.yaml` | Flight, hotel, activity, geocoding, event (ClusterIP) |
| `deploy/openshift/backend.yaml`         | Orchestrator + Route                                  |
| `deploy/openshift/frontend.yaml`        | Frontend                                              |
| `deploy/openshift/storage.yaml`         | PVC output                                            |
| `deploy/openshift/monitoring/`          | Prometheus, Grafana, PVC                              |


Grafana và Prometheus chỉ có trên cluster này, không phải stack Compose local.

---

