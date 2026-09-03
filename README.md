
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
![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![OpenShift](https://img.shields.io/badge/Red%20Hat%20OpenShift-EE0000?style=for-the-badge&logo=redhatopenshift&logoColor=white)
![Nginx](https://img.shields.io/badge/Nginx-009639?style=for-the-badge&logo=nginx&logoColor=white)
![RapidAPI](https://img.shields.io/badge/RapidAPI-005571?style=for-the-badge&logo=rapidapi&logoColor=white)

An **AI Travel Agent** built with a **Distributed Microservices Architecture**. The system leverages **LangGraph** for stateful multi-agent orchestration, **FastAPI** for high-performance service communication, and **React** for the frontend.

It demonstrates a scalable, self-correcting AI system capable of planning, researching, evaluating, and generating detailed travel itineraries by orchestrating a fleet of specialized microservices (Flight, Hotel, Activity, Event, Geocoding).

---

## Overview

This project represents a **cloud-native AI Travel Agent** re-architected from a monolithic application into a **distributed microservices system**.

The application is orchestrated via **Docker** and creates a seamless ecosystem of 7 **independent containers**:

1- **Frontend:** A high-performance React UI served by Nginx.

2- **Orchestrator (Backend):** The central nervous system powered by **LangGraph**, responsible for managing state, LLM reasoning (Groq/Llama 3), and plan evaluation.

3- **5 Specialized Microservices:** Dedicated FastAPI containers for **Flight Search, Hotel Search, Event Discovery, Activity Extraction, and Geocoding**.

A user interacts with the web interface to submit a natural language request. The **Orchestrator** parses this intent and triggers parallel requests to the microservices, drastically reducing latency. It then aggregates real-time data from **Booking.com, Ticketmaster, and Tavily**, applies intelligent self-correction via an **Evaluator Agent** (Gemini), and produces a fully detailed itinerary.

Designed for **scalability and fault tolerance**, this project demonstrates advanced engineering principles suitable for enterprise cloud platforms like **Red Hat OpenShift**.

---

## Features

- **Distributed Microservices Architecture:** The backend is decoupled into 6 distinct containers:

  - **Orchestrator:** Manages state, LangGraph workflow, and LLM reasoning.

  - **Flight Service:** Dedicated microservice for parallel flight search and filtering (Booking.com API).

  - **Hotel Service:** Dedicated microservice for accommodation search (Booking.com API).

  - **Event Service:** Dedicated microservice for real-time event discovery (Ticketmaster API).

  - **Activity Service:** Web scraper microservice for local attractions (Tavily API).

  - **Geocoding Service:** Utility microservice for coordinate mapping with Rate Limiting (OpenStreetMap).

- **Automated OpenShift Deployment:** Includes a custom Bash script (`deploy_all.sh`) for one-click build and deployment of all 7 containers to Red Hat OpenShift (CRC).

- **Autonomous Multi-Agent System:** Uses LangGraph to manage a team of specialized agents (Planner, Researcher, Flight/Hotel/Event Specialists, Evaluator) that collaborate to achieve a complex goal.

- **Parallel Execution:** The Orchestrator triggers Flight, Hotel, and Event services simultaneously, significantly reducing total request latency.

- **Resilient & Fault Tolerant:** Designed to handle service timeouts gracefully. If a non-critical service (e.g., Geocoding) fails, the Orchestrator adapts and continues the pipeline.

- **Intelligent Self-Correction:** An Evaluator Agent (Gemini) critiques the generated plan against budget/constraints and triggers targeted refinement loops if necessary.


---

## System Architecture

The application is containerized using **Docker** and orchestrated via **Docker Compose** (for local dev) or **Kubernetes/OpenShift** (for production).

### Microservices Communication Flow

```mermaid
graph TD
    User((User)) -->|HTTP/React| Frontend[Frontend Container<br>React + Nginx]
    Frontend -->|JSON Stream| Orch[Orchestrator Container<br>FastAPI + LangGraph]
    
    subgraph "Internal Service Network"
        Orch -->|HTTP/REST| Flight[Flight Service]
        Orch -->|HTTP/REST| Hotel[Hotel Service]
        Orch -->|HTTP/REST| Event[Event Service]
        Orch -->|HTTP/REST| Activity[Activity Service]
        Orch -->|HTTP/REST| Geo[Geocoding Service]
    end
    
    subgraph "External APIs"
        Flight --> BookingAPI(Booking.com)
        Hotel --> BookingAPI
        Event --> TM(Ticketmaster)
        Activity --> Tavily(Tavily Search)
        Geo --> OSM(OpenStreetMap)
        Orch --> LLM(Groq Llama 3 & Gemini)
    end
 ```

### The Agentic Workflow (Inside Orchestrator)

- **Planner Node:** Structured parsing of user intent.

- **Parallel Execution:** Calls Flight, Hotel, and Event microservices concurrently.

- **Aggregator:** Synchronizes results.

- **Activity & Geocoding:** Calls Activity Service for POIs and Geocoding Service for coordinates.

- **Scheduler & Evaluator:** Organizes the timeline and uses Gemini to audit the budget.

- **Refinement Loop:** If rejected, routes back to specific services for better options.

---

## Tech Stack

Category | Tool/Library | Purpose |
:---| :--- | :--- |
| `Infrastructure` | **Docker & Docker Compose** | Local containerization and multi-container orchestration. |
| | **Red Hat OpenShift (CRC)** | Enterprise Kubernetes cluster for production-grade deployment. |
| | **Nginx** | Serving the React frontend production build. |
`AI& Orchestration`  | **Groq(Llama 3)** | High-speed generation for planning and scheduling. |
| | **Google Gemini** | "High IQ" evaluator for plan auditing. |
| | **LangChain** | Core framework for LLM interactions and tool definitions. |
| | **LangGraph** | Orchestrates the stateful, multi-agent graph with cycles and parallel execution. |
| | **Pydantic** | Ensures data is structured and reliable throughout the entire workflow. |
`Backend` | **FastAPI** | A high-performance Python framework for building the API server. |
| | **Uvicorn** | The ASGI server that runs the FastAPI application.  |
| | **Python 3.10+** | The core programming language for the backend and agent logic. |
| | **Folium & Geopy** | Map generation and geocoding. |
`Frontend` | **React & Vite** |Building the interactive user interface. |
| | **Axios** | Making HTTP requests from the client to the backend API. |
| | **React-Markdown** | Rendering the final Markdown report beautifully in the UI.|
| `Data Source` | **RapidAPI** | Platform for accessing live Flight and Hotel APIs.|
| | **Tavily** | Live web search for finding real-time activity information.
| | **Ticketmaster** | Live API for discovering concerts, sports, and other events. 


---

##  Installation & Local Setup

#### Prerequisites

- Docker Desktop installed and running.

- API Keys for Groq, Gemini, Tavily, RapidAPI, and Ticketmaster.

#### 1. Clone & Configure

```bash
git clone https://github.com/berkyalkn/AI-travel-agent
cd AI-travel-agent

# Create centralized .env file
cd server
touch .env
```

Add your keys to `server/.env`:

```bash
GROQ_API_KEY=...
GEMINI_API_KEY=...
TAVILY_API_KEY=...
RAPIDAPI_KEY=...
TICKETMASTER_API_KEY=...
```


#### 2. Run with Docker Compose

This single command spins up **7** containers (Frontend, Orchestrator, 5 Microservices) and sets up the internal network.

```bash
# Return to root directory
cd ..
docker-compose up --build
```

Wait until you see `Uvicorn running on http://0.0.0.0:8000` in the logs and access the application at http://localhost:3000.

---
## Cloud Deployment (OpenShift / K8s)

The project includes a production-ready OpenShift configuration with resource limits, recreating strategies, and PVCs..

#### Automated Deployment (Recommended):

Instead of manually applying YAMLs for 7 services, use the included automation script.

**1- Login to OpenShift:**

```bash
oc login -u developer -p developer https://api.crc.testing:6443
```

**2- Run the Deployment Script:** This script builds all images, pushes them to Docker Hub, applies Kubernetes manifests, creates Secrets/PVCs, and links the Frontend to the Backend dynamically.

```bash
chmod +x deploy_all.sh
./deploy_all.sh
```

#### Manual Deployment (Architecture Details)

If you prefer manual control, the manifests are located in `openshift/`:

- `openshift/microservices/*.yaml`: Definitions for internal services (ClusterIP only).

- `openshift/backend-deployment.yaml`: Orchestrator config with PVC and Route.

- `openshift/frontend-deployment.yaml`: Frontend config.

---

## 📂 Project Structure

```plaintext
AI-travel-agent/
├── client/                     # React Frontend Application (Vite + Nginx)
├── server/                     # ORCHESTRATOR
│   ├── services/               # MICROSERVICES (Independent Containers)
│   │   ├── flight-service/     # Flight Search Logic (FastAPI + Booking API)
│   │   ├── hotel-service/      # Hotel Search Logic (FastAPI + Booking API)
│   │   ├── event-service/      # Event Discovery Logic (FastAPI + Ticketmaster)
│   │   ├── activity-service/   # Activity Scraping Logic (FastAPI + Tavily)
│   │   └── geocoding-service/  # Coordinate Mapping Logic (FastAPI + OSM)
│   ├── output/                 # Shared Volume for Generated Reports (.md/.html)
│   ├── agent.py                # LangGraph Workflow DAG Definitions
│   ├── nodes.py                # Agent Functions & LLM Proxy Logic
│   ├── main.py                 # Orchestrator FastAPI Entry Point
│   ├── schemas.py              # Central Pydantic Data Models
│   ├── state.py                # TripState Type Definitions
│   ├── Dockerfile              # Orchestrator Image Build Instruction
│   ├── requirements.txt        # Orchestrator Python Dependencies
│   └── .dockerignore           # Docker Build Optimization
├── openshift/                  # Kubernetes/OpenShift Deployment Manifests
├── deploy_all.sh               # Automated Build & Deploy Script
├── docker-compose.yaml         # Local Development Orchestration (7 Containers)
├── .gitignore                  # Git Ignore Rules
└── README.md                   # Project Documentation
```

---

## Key Engineering Concepts

This project serves as a showcase of advanced AI Engineering and Cloud Architecture principles:

#### AI & Agentic Patterns

- **Stateful Multi-Agent Orchestration:** Uses LangGraph to manage a complex, cyclic workflow where specialized agents (Planner, Researcher, Evaluator) collaborate through a persistent state (TripState), mimicking a human team structure.

- **Structured Output & Validation:** Enforces strict Pydantic schemas on all LLM outputs. This prevents hallucinations in data structures and ensures the frontend receives reliable, parseable JSON for rendering.

- **Intelligent Self-Correction (Reflection):** Implements a feedback loop inspired by Constitutional AI. The Evaluator Agent critiques the plan against constraints (budget, location). If rejected, it dynamically routes the workflow back to specific agents for targeted refinement, rather than restarting the whole process.

- **Tool Use & Live Grounding:** Demonstrates advanced tool binding where LLMs autonomously query real-time APIs (Booking.com, Ticketmaster, Tavily) to ground their reasoning in current, real-world data.


#### Cloud & System Architecture

- **Microservices Pattern:** Decouples the application into a Frontend container, an Orchestrator container, and 5 specialized Microservice containers, communicating via a custom bridge network. This ensures independent scaling and strict separation of concerns.

- **Containerization & Security:** Fully dockerized environment following OpenShift security standards (non-root users, arbitrary UID support).

- **Automated DevOps Pipeline:** Includes a custom Bash script (deploy_all.sh) that automates the entire CI/CD-like process: building 7 Docker images, pushing to registry, applying Kubernetes manifests, and dynamically linking services via OpenShift Routes.

- **Resilient Error Handling:** Implements robust retry mechanisms (exponential backoff) and timeout handling for external APIs (e.g., Geocoding), ensuring system stability even during network latency or API outages.

- **Parallel Execution:** Optimizes performance by executing independent blocking I/O operations (Flight, Hotel, and Event searches) concurrently via the Orchestrator.

- **Cloud-Native Deployment Strategy:** The application is architected to run on Kubernetes/OpenShift. It respects strict security contexts (Arbitrary UID), uses Secrets for sensitive key management, and implements Service Discovery via OpenShift Routes.

### What You Get

Upon successful execution, the system generates comprehensive outputs accessible via both the Web UI and the local file system:

- **Interactive Web Dashboard:** A real-time UI that streams the agent's thought process and renders the final plan.

- **Smart Budget Breakdown:** A comparative analysis of the estimated cost vs. user budget, including per-person calculations.

- **Rich Markdown Report (trip_itinerary.md):** A detailed, readable document containing flight tables, hotel ratings, and day-by-day schedules.

- **Interactive Map (trip_itinerary.html):** A generated HTML file with an embedded Leaflet/Folium map, plotting every activity with numbered markers for spatial visualization.