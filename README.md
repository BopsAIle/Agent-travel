# Autonomous AI Travel Agent (Microservices Architecture)

![React](https://img.shields.io/badge/React-20232A?style=for-the-badge&logo=react&logoColor=61DAFB)
![Vite](https://img.shields.io/badge/Vite-646CFF?style=for-the-badge&logo=vite&logoColor=white)
![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)
![Pydantic](https://img.shields.io/badge/Pydantic-E92063?style=for-the-badge&logo=pydantic&logoColor=white)
![LangChain](https://img.shields.io/badge/LangChain-1C3C3C?style=for-the-badge&logo=langchain&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-E10098?style=for-the-badge&logo=langchain&logoColor=white)
![Google Gemini](https://img.shields.io/badge/Google%20Gemini-8E75B2?style=for-the-badge&logo=google%20gemini&logoColor=white)
![Groq](https://img.shields.io/badge/Groq-F55036?style=for-the-badge&logo=groq&logoColor=white)
![Meta Llama 3](https://img.shields.io/badge/Meta%20Llama%203-0467DF?style=for-the-badge&logo=meta&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![OpenShift](https://img.shields.io/badge/Red%20Hat%20OpenShift-EE0000?style=for-the-badge&logo=redhatopenshift&logoColor=white)
![Prometheus](https://img.shields.io/badge/Prometheus-E6522C?style=for-the-badge&logo=prometheus&logoColor=white)
![Grafana](https://img.shields.io/badge/Grafana-F46800?style=for-the-badge&logo=grafana&logoColor=white)
![Nginx](https://img.shields.io/badge/Nginx-009639?style=for-the-badge&logo=nginx&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-2088FF?style=for-the-badge&logo=githubactions&logoColor=white)

An **Autonomous AI Travel Agent** built with a **Distributed Microservices Architecture**. The system leverages **LangGraph** for stateful multi-agent orchestration, **FastAPI** for high-performance service communication, **PostgreSQL with pgvector** for persistent memory, and **React** for the frontend.

It demonstrates a production-grade, self-correcting AI system capable of holding natural conversations, learning user preferences across sessions, and generating detailed travel itineraries by orchestrating a fleet of specialized microservices (Flight, Hotel, Activity, Event, Geocoding).

---

## Overview

This project is a **cloud-native AI Travel Agent** built with a fully **distributed microservices architecture**. Users interact with a conversational chat interface — the system understands natural language, maintains multi-session memory, and autonomously plans entire trips by querying real-time travel APIs in parallel.

The application runs as **9+ independent containers** orchestrated via Docker Compose (local) or Kubernetes/OpenShift (production):

1. **Frontend:** A React 19 + Vite SPA served by Nginx with real-time SSE streaming.
2. **Orchestrator (Backend):** The central brain — FastAPI + LangGraph + LLM reasoning (Groq/Llama 3 & Gemini).
3. **PostgreSQL + pgvector:** Persistent database for users, chat history, and vector-embedded long-term memory.
4. **5 Specialized Microservices:** Independent FastAPI containers for Flight, Hotel, Event, Activity, and Geocoding.
5. **Monitoring Stack:** Prometheus + Grafana for real-time metrics and dashboards.

A user submits a natural language travel request. A **Supervisor Agent** classifies intent and manages the conversation. For trip planning, it triggers a **LangGraph pipeline** that calls microservices in parallel, aggregates real-time data from **Booking.com, Ticketmaster, and Tavily**, applies intelligent self-correction via an **Evaluator Agent** (Gemini), and streams a fully detailed itinerary back to the user. The system also **learns traveler preferences** (home city, budget style, dietary needs, etc.) and retrieves relevant past trips using vector similarity search.

---

## Features

### 🤖 Conversational & Agentic
- **Natural Language Chat Interface:** Full multi-turn conversation with session persistence and history sidebar.
- **Supervisor Agent:** Classifies each message, manages conversation slots, and decides when to trigger the full trip planner.
- **Autonomous Multi-Agent Pipeline:** LangGraph orchestrates a team of specialized agents (Planner, Researcher, Flight/Hotel/Event Specialists, Evaluator) through a stateful, cyclic workflow.
- **Intelligent Self-Correction:** An Evaluator Agent (Gemini) critiques the generated plan against budget/constraints and triggers targeted refinement loops if needed.

### 🧠 Long-Term Memory
- **Three-Tier Memory System:**
  - **Working Memory:** In-session state — conversation slots and messages.
  - **Episodic Memory:** Past trips stored with vector embeddings; retrieved by semantic similarity for context.
  - **Semantic Memory:** Durable traveler profile (`UserFact`) — home city, budget preferences, dietary needs, hotel style — persisted across sessions via `pgvector`.

### 🏗️ Microservices Architecture
- **Flight Service:** Parallel IATA lookup and round-trip flight search (Booking.com via RapidAPI).
- **Hotel Service:** Accommodation search (Booking.com via RapidAPI).
- **Event Service:** Real-time event discovery (Ticketmaster API).
- **Activity Service:** Local attraction extraction via web search (Tavily API).
- **Geocoding Service:** Coordinate mapping with rate limiting (OpenStreetMap/Nominatim).

### ⚡ Performance & Reliability
- **Parallel Execution:** Flight, Hotel, and Event services run concurrently, minimizing total latency.
- **Real-Time Streaming:** Agent progress is streamed to the UI via Server-Sent Events (SSE).
- **Resilient Error Handling:** Exponential backoff, timeout handling, and graceful degradation if non-critical services fail.

### 🔐 Authentication & Security
- **JWT-Based Auth:** Secure user registration and login with `PyJWT` + `bcrypt` password hashing.
- **Per-User Isolation:** Each user has private chat history, memory, and traveler profile.
- **OpenShift-Ready Security:** Non-root containers with arbitrary UID support.

### 📊 Observability
- **Prometheus Metrics:** Auto-instrumented via `prometheus-fastapi-instrumentator` — request counts, latencies, agent run durations, API costs.
- **Grafana Dashboards:** Pre-configured dashboards for visualizing service health and agent telemetry.
- **Full Telemetry:** Every agent run and span is stored in PostgreSQL (`AgentRunRow`, `AgentSpanRow`) for cost tracking and debugging.

### 🚀 DevOps & CI/CD
- **GitHub Actions CI Pipeline:** Automated linting and build checks on every push.
- **Docker Compose:** One-command local dev environment with all containers.
- **Automated OpenShift Deployment:** `deploy_all.sh` — builds all images, pushes to Docker Hub, and applies all Kubernetes manifests in one step.

---

## System Architecture

### Microservices Communication Flow

```mermaid
graph TD
    User((User)) -->|HTTP + SSE| Frontend[Frontend Container<br>React 19 + Nginx]
    Frontend -->|JSON Stream /chat-stream| Orch[Orchestrator Container<br>FastAPI + LangGraph]

    Orch <-->|SQL + pgvector| DB[(PostgreSQL 16<br>+ pgvector)]

    subgraph "Internal Service Network"
        Orch -->|HTTP/REST| Flight[Flight Service]
        Orch -->|HTTP/REST| Hotel[Hotel Service]
        Orch -->|HTTP/REST| Event[Event Service]
        Orch -->|HTTP/REST| Activity[Activity Service]
        Orch -->|HTTP/REST| Geo[Geocoding Service]
    end

    subgraph "External APIs"
        Flight --> BookingAPI(Booking.com / RapidAPI)
        Hotel --> BookingAPI
        Event --> TM(Ticketmaster)
        Activity --> Tavily(Tavily Search)
        Geo --> OSM(OpenStreetMap)
        Orch --> LLM(Groq Llama 3 & Google Gemini)
    end

    subgraph "Monitoring"
        Orch -->|/metrics| Prom[Prometheus]
        Prom --> Grafana[Grafana]
    end
```

### The Agentic Workflow (Inside Orchestrator)

```
User Message
     │
     ▼
[Supervisor Agent]  ──── Retrieves memory, classifies intent
     │
     ▼ (trip intent detected)
[Planner Node]      ──── Parses destination, dates, budget, travelers
     │
     ▼ (parallel)
[Flight Agent] ─────────────────────────────────────────────┐
[Hotel Agent]  ──────────────────────────────────────────── │
[Event Agent]  ──────────────────────────────────────────── │
     │                                                       │
     ▼ (aggregate)                                           │
[Aggregator]   ◄────────────────────────────────────────────┘
     │
     ▼
[Activity Extractor]  ──── Tavily web search for local POIs
     │
     ▼
[Geocoding Agent]     ──── Coordinate mapping for all locations
     │
     ▼
[Scheduler]           ──── Day-by-day itinerary generation
     │
     ▼
[Evaluator Agent]     ──── Gemini audits budget & constraints
     │
     ├── [PASS] ──► [Map Generator] ──► [Report Formatter] ──► Final Itinerary
     │
     └── [FAIL] ──► back to Flight/Hotel/Event for refinement (loop)
```

---

## Tech Stack

| Category | Tool / Library | Purpose |
| :--- | :--- | :--- |
| **Frontend** | React 19 + Vite 7 | Interactive SPA |
| | Nginx | Serves production React build |
| | `@microsoft/fetch-event-source` | SSE real-time streaming |
| | `react-markdown` + `remark-gfm` | Rich itinerary rendering |
| | `framer-motion` | UI animations |
| **AI & Orchestration** | LangGraph | Stateful multi-agent DAG with cycles and parallel branches |
| | LangChain | LLM integrations and tool definitions |
| | Groq (Llama 3) | High-speed planner, scheduler, and supervisor LLM |
| | Google Gemini | "High IQ" evaluator/critic for plan auditing |
| | Pydantic | Structured outputs and schema validation throughout |
| **Backend** | FastAPI + Uvicorn | High-performance async API server |
| | Python 3.10+ | Core language for all server-side logic |
| | Folium + Geopy | Interactive map generation and geocoding |
| **Database** | PostgreSQL 16 + pgvector | Users, sessions, messages, and vector-embedded memory |
| | SQLAlchemy 2.0 | ORM for all database interactions |
| **Auth** | PyJWT + bcrypt | JWT-based authentication and password hashing |
| **Observability** | Prometheus | Metrics collection and instrumentation |
| | Grafana | Real-time dashboards |
| | `prometheus-fastapi-instrumentator` | Auto-instrument FastAPI endpoints |
| **Data Sources** | Booking.com (RapidAPI) | Live flight and hotel search |
| | Ticketmaster API | Event and concert discovery |
| | Tavily Search API | Real-time web search for activities |
| | OpenStreetMap (Nominatim) | Free geocoding and coordinate mapping |
| **Infrastructure** | Docker + Docker Compose | Local containerization and orchestration |
| | Red Hat OpenShift (CRC) | Production Kubernetes cluster |
| **CI/CD** | GitHub Actions | Automated CI pipeline |

---

## Installation & Local Setup

### Prerequisites

- Docker Desktop installed and running
- API Keys for: **Groq**, **Gemini**, **Tavily**, **RapidAPI** (Booking.com), **Ticketmaster**

### 1. Clone & Configure

```bash
git clone https://github.com/your-username/AI-travel-agent
cd AI-travel-agent
```

Create the environment file:

```bash
# server/.env
GROQ_API_KEY=your_groq_key
GEMINI_API_KEY=your_gemini_key
TAVILY_API_KEY=your_tavily_key
RAPIDAPI_KEY=your_rapidapi_key
TICKETMASTER_API_KEY=your_ticketmaster_key

DATABASE_URL=postgresql://travel:travel@travel-postgres:5432/travel_agent
JWT_SECRET=change-me-in-production
JWT_EXPIRE_HOURS=72
```

### 2. Run with Docker Compose

This single command spins up all containers (Frontend, Orchestrator, PostgreSQL, 5 Microservices, Prometheus, Grafana) and configures the internal network:

```bash
docker-compose up --build
```

| Service | URL |
| :--- | :--- |
| **Web App** | http://localhost:3000 |
| **API (Orchestrator)** | http://localhost:5001 |
| **Grafana Dashboard** | http://localhost:3001 |
| **Prometheus** | http://localhost:9090 |

Wait until you see `Uvicorn running on http://0.0.0.0:8000` for the orchestrator, then open http://localhost:3000.

---

## Cloud Deployment (OpenShift / Kubernetes)

### Automated Deployment (Recommended)

**1. Login to OpenShift:**

```bash
oc login -u developer -p developer https://api.crc.testing:6443
```

**2. Run the deployment script:**

This script builds all images, pushes them to Docker Hub, applies all Kubernetes manifests, creates Secrets and PVCs, and dynamically links the frontend to the backend via OpenShift Routes.

```bash
chmod +x deploy_all.sh
./deploy_all.sh
```

### Manual Deployment

Manifests are located in `openshift/`:

- `openshift/microservices/*.yaml` — Internal services (ClusterIP only)
- `openshift/backend-deployment.yaml` — Orchestrator config with PVC and Route
- `openshift/frontend-deployment.yaml` — Frontend config
- `openshift/monitoring/` — Prometheus + Grafana deployment YAMLs

---

## Project Structure

```plaintext
AI-travel-agent/
├── client/                         # React 19 + Vite Frontend (served by Nginx)
│   └── src/
│       ├── components/             # ChatWindow, AgentMonitor, LoginScreen, etc.
│       ├── context/                # AuthContext (JWT session management)
│       ├── App.jsx                 # Root — SSE streaming and session state
│       ├── api.js                  # API helper functions
│       └── chatHistory.js         # Chat history utilities
│
├── server/                         # ORCHESTRATOR (FastAPI + LangGraph)
│   ├── services/                   # MICROSERVICES (each is an independent container)
│   │   ├── flight-service/         # Flight search — Booking.com + IATA lookup
│   │   ├── hotel-service/          # Hotel search — Booking.com
│   │   ├── event-service/          # Event discovery — Ticketmaster
│   │   ├── activity-service/       # Activity extraction — Tavily web search
│   │   └── geocoding-service/      # Coordinate mapping — OpenStreetMap
│   ├── agents/
│   │   └── supervisor.py           # Conversation turn controller + intent classifier
│   ├── db/                         # SQLAlchemy models, session factory, base
│   ├── memory/                     # Three-tier memory (episodic, semantic, working)
│   │   ├── episodic.py             # Past trips with vector embeddings
│   │   ├── semantic.py             # Durable traveler profile (UserFact)
│   │   ├── working.py              # In-session state
│   │   ├── embed.py                # Embedding utilities (pgvector)
│   │   └── manager.py              # Unified memory retrieval
│   ├── output/                     # Generated reports (.md) and maps (.html)
│   ├── agent.py                    # LangGraph StateGraph DAG definition
│   ├── nodes.py                    # All agent node functions
│   ├── main.py                     # FastAPI entry point & SSE endpoints
│   ├── schemas.py                  # Central Pydantic data models
│   ├── state.py                    # TripState TypedDict
│   ├── conversation.py             # Chat session management
│   ├── auth.py                     # JWT authentication logic
│   ├── telemetry.py                # Agent run / span tracking
│   ├── metrics.py                  # Prometheus metrics definitions
│   ├── Dockerfile                  # Orchestrator image
│   └── requirements.txt
│
├── openshift/                      # Kubernetes/OpenShift Manifests
│   ├── microservices/              # Per-service ClusterIP YAMLs
│   └── monitoring/                 # Prometheus + Grafana YAMLs
│
├── .github/
│   └── workflows/
│       └── ci-pipeline.yml         # GitHub Actions CI
│
├── docker-compose.yaml             # Full local dev stack (9+ containers)
├── deploy_all.sh                   # Automated OpenShift build & deploy script
├── .gitignore
└── README.md
```

---

## Key Engineering Concepts

### AI & Agentic Patterns

- **Stateful Multi-Agent Orchestration:** LangGraph manages a complex, cyclic workflow where specialized agents collaborate through a persistent `TripState`, mimicking a human planning team.
- **Three-Tier Memory Architecture:** Combines in-session working memory with long-term episodic and semantic memory via `pgvector` embeddings — enabling the agent to remember and learn from past interactions.
- **Structured Output & Validation:** Pydantic schemas enforce strict structure on all LLM outputs, preventing hallucinations in JSON data and ensuring reliable rendering on the frontend.
- **Intelligent Self-Correction (Reflection):** The Evaluator Agent critiques the plan against constraints; if rejected, it routes the workflow back to specific agents for targeted refinement rather than restarting.
- **Tool Use & Live Grounding:** LLMs autonomously query real-time APIs (Booking.com, Ticketmaster, Tavily) to ground reasoning in current, real-world data.

### Cloud & System Architecture

- **Microservices Pattern:** Decoupled into 7+ independent containers communicating via a custom bridge network, ensuring independent scaling and strict separation of concerns.
- **Containerization & Security:** Fully Dockerized with OpenShift security standards — non-root users, arbitrary UID support, Secrets for API key management.
- **Automated DevOps Pipeline:** `deploy_all.sh` automates the entire CI/CD-like process: building images, pushing to a registry, and applying all Kubernetes manifests dynamically.
- **Resilient Error Handling:** Retry mechanisms with exponential backoff and timeout handling for all external APIs, ensuring stability under network latency or API outages.
- **Parallel Execution:** Independent I/O-bound tasks (Flight, Hotel, Event searches) execute concurrently via the LangGraph DAG, minimizing total latency.
- **Observability-First:** Every API request, agent run, and span is tracked — Prometheus metrics, Grafana dashboards, and PostgreSQL-persisted telemetry provide full visibility into system behavior.

---

## What You Get

Upon successful execution, the system produces:

- **Real-Time Chat Interface:** Streams the agent's thought process step-by-step, with full conversation history.
- **Detailed Day-by-Day Itinerary:** Flights, hotels, activities, and events organized into a complete trip schedule.
- **Smart Budget Breakdown:** Comparative analysis of estimated cost vs. user budget, including per-person calculations.
- **Rich Markdown Report (`trip_itinerary.md`):** A readable document with flight tables, hotel ratings, and the full schedule.
- **Interactive Map (`trip_itinerary.html`):** An embedded Leaflet/Folium map plotting every activity with numbered markers for spatial visualization.
- **Personalized Recommendations:** The system learns your preferences (budget style, dietary needs, hotel preferences) and applies them automatically in future sessions.
