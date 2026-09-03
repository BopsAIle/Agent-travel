import json
import asyncio
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy.orm import Session

from agent import app as travel_agent_app
from agents.supervisor import after_plan_complete, run_supervised_turn
from auth import (
    create_access_token,
    get_current_user,
    get_user_by_email,
    hash_password,
    verify_password,
)
from conversation import (
    determine_refresh,
    synthesize_user_request,
    build_graph_state,
    slots_snapshot,
    summarize_completed_plan,
)
from places import looks_like_place_request
from db.models import User
from db.session import SessionLocal, get_db, init_db
from memory.semantic import get_or_create_profile
from memory.working import (
    delete_session,
    export_session,
    get_or_create_session,
    list_session_summaries,
    load_session,
    restore_session,
)
from metrics import agent_metrics_overview, agent_run_detail
from schemas import AuthRequest, AuthResponse, ChatRequest, RestoreChatRequest
from telemetry import bind_run, persist_run, start_run


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="AI Travel Agent API",
    description="An API to generate travel itineraries using a multi-agent system.",
    lifespan=lifespan,
)


origins = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://travel-frontend-route-travel-agent-project.apps-crc.testing"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Instrumentator().instrument(app).expose(app)

class PlanRequest(BaseModel):
    user_query: str


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


def _auth_payload(user: User) -> AuthResponse:
    return AuthResponse(
        access_token=create_access_token(user),
        user_id=str(user.id),
        email=user.email,
    )


@app.get("/")
def read_root():
    return {"status": "AI Travel Agent API is running."}


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/auth/register", response_model=AuthResponse)
def register(payload: AuthRequest, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Invalid email.")
    if get_user_by_email(db, email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered.")
    user = User(email=email, password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    get_or_create_profile(db, user.id)
    return _auth_payload(user)


@app.post("/auth/login", response_model=AuthResponse)
def login(payload: AuthRequest, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    user = get_user_by_email(db, email)
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")
    return _auth_payload(user)


@app.get("/auth/me")
def me(user: User = Depends(get_current_user)):
    return {"user_id": str(user.id), "email": user.email}


@app.get("/chats")
def list_chats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"chats": list_session_summaries(db, user.id)}


@app.get("/chats/{session_id}")
def get_chat(session_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    session = load_session(db, user.id, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat not found.")
    return export_session(session)


@app.put("/chats/{session_id}")
def put_chat(
    session_id: str,
    request: RestoreChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = restore_session(
        db,
        user.id,
        session_id,
        request.messages,
        request.slots,
        request.language,
        request.has_plan,
    )
    return export_session(session)


@app.delete("/chats/{session_id}")
def remove_chat(session_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not delete_session(db, user.id, session_id):
        raise HTTPException(status_code=404, detail="Chat not found.")
    return {"ok": True}


@app.get("/metrics/agents")
def metrics_agents(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return agent_metrics_overview(db, user.id)


@app.get("/metrics/runs/{run_id}")
def metrics_run(run_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        parsed = uuid.UUID(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Run not found.") from exc
    detail = agent_run_detail(db, user.id, parsed)
    if not detail:
        raise HTTPException(status_code=404, detail="Run not found.")
    return detail


@app.post("/chat-stream")
async def chat_stream(request: ChatRequest, user: User = Depends(get_current_user)):
    if os.getenv("MOCK_MODE") == "True":
        async def mock_chat_stream():
            yield sse("session", {"session_id": request.session_id or "mock-session"})
            yield sse("slots", {})
            yield sse("message", {"role": "assistant", "content": "TEST MODE: Planning trip..."})
            await asyncio.sleep(0.3)
            yield sse("status", {"message": "TEST MODE: Calling Flight Service..."})
            await asyncio.sleep(0.3)
            yield sse(
                "final_report",
                {
                    "markdown_report": "# Test Report\n\nThis is a generated response for Load Testing.",
                    "map_html": None,
                },
            )
        return StreamingResponse(mock_chat_stream(), media_type="text/event-stream")

    async def event_stream():
        db = SessionLocal()
        telemetry = None
        run_status = "ok"
        run_error = None
        route = None
        try:
            session = get_or_create_session(db, user.id, request.session_id)
            yield sse("session", {"session_id": session.session_id})
            telemetry = start_run(user.id, session.session_id, kind="chat")
            if looks_like_place_request(request.message):
                language = session.language or "en"
                yield sse("status", {"message": status_for_node("place_lookup", language)})

            def supervised():
                bind_run(telemetry)
                return run_supervised_turn(db, session, request.message)

            result = await asyncio.to_thread(supervised)
            route = result.route
            telemetry.route = result.route
            yield sse("slots", slots_snapshot(session.slots))
            yield sse("message", {"role": "assistant", "content": result.turn.reply})
            yield sse("route", {"route": result.route})

            if not result.should_plan:
                return

            refresh = determine_refresh(
                result.previous_slots,
                session.slots,
                result.turn.intent,
                result.turn.refine_targets,
                session.has_plan,
            )
            user_request = synthesize_user_request(
                session.slots,
                request.message,
                session.user_feedback,
                memory_context=result.bundle.as_planner_context(),
            )
            initial_state = build_graph_state(
                session,
                refresh,
                user_request,
                memory_context=result.bundle.as_planner_context(),
            )
            initial_state["telemetry_run_id"] = telemetry.id
            language = session.language or "en"

            full_state = dict(initial_state)
            async for chunk in travel_agent_app.astream(initial_state):
                for node_name, node_output in chunk.items():
                    if isinstance(node_output, dict):
                        full_state.update(node_output)
                    yield sse("status", {"message": status_for_node(node_name, language)})
                    await asyncio.sleep(0.05)

            full_state.pop("telemetry_run_id", None)
            session.trip_state = full_state
            session.has_plan = bool(full_state.get("final_itinerary") and full_state.get("markdown_report"))
            session.markdown_report = full_state.get("markdown_report")

            def summarize():
                bind_run(telemetry)
                return summarize_completed_plan(language, full_state)

            summary = await asyncio.to_thread(summarize)
            session.messages.append({"role": "assistant", "content": summary})
            yield sse("message", {"role": "assistant", "content": summary})

            yield sse(
                "final_report",
                {
                    "markdown_report": full_state.get("markdown_report"),
                    "map_html": full_state.get("map_html"),
                },
            )

            def finish_plan():
                bind_run(telemetry)
                after_plan_complete(db, session)

            await asyncio.to_thread(finish_plan)
        except Exception as e:
            run_status = "error"
            run_error = str(e)
            print(f"AN ERROR OCCURRED during chat stream: {e}")
            yield sse("error", {"message": f"An error occurred: {e}"})
        finally:
            if telemetry is not None:
                try:
                    persist_run(db, telemetry, status=run_status, error=run_error, route=route)
                except Exception as persist_exc:
                    print(f"-> Failed to persist agent run: {persist_exc}")
            db.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/plan-trip-stream")
async def plan_trip_stream(request: PlanRequest, user: User = Depends(get_current_user)):

    if os.getenv("MOCK_MODE") == "True":
        async def mock_event_stream():
            yield f"event: status\ndata: {json.dumps({'message': 'TEST MODE: Planning trip...'})}\n\n"
            await asyncio.sleep(0.5)

            yield f"event: status\ndata: {json.dumps({'message': 'TEST MODE: Calling Flight Service...'})}\n\n"
            await asyncio.sleep(0.5)

            yield f"event: status\ndata: {json.dumps({'message': 'TEST MODE: Generating report...'})}\n\n"
            await asyncio.sleep(0.5)

            final_data = {
                "markdown_report": "# Test Report\n\nThis is a generated response for Load Testing.",
                "map_html": None
            }
            yield f"event: final_report\ndata: {json.dumps(final_data)}\n\n"

        return StreamingResponse(mock_event_stream(), media_type="text/event-stream")

    initial_state = {
        "user_request": request.user_query,
        "user_id": str(user.id),
        "memory_context": "",
    }

    async def event_stream():
        db = SessionLocal()
        telemetry = start_run(user.id, None, kind="plan")
        initial_state["telemetry_run_id"] = telemetry.id
        run_status = "ok"
        run_error = None
        try:
            node_output = {}
            full_state = dict(initial_state)
            async for chunk in travel_agent_app.astream(initial_state):
                for key, value in chunk.items():
                    node_name = key
                    node_output = value
                    if isinstance(value, dict):
                        full_state.update(value)

                    status_message = f"Working on: {node_name.replace('_', ' ').title()}"
                    print(f"Streaming status: {status_message}")

                    yield f"event: status\ndata: {json.dumps({'message': status_message})}\n\n"
                    await asyncio.sleep(0.1)

            final_report_markdown = full_state.get("markdown_report") or (
                node_output.get("markdown_report") if isinstance(node_output, dict) else None
            )
            map_html_content = full_state.get("map_html") or (
                node_output.get("map_html") if isinstance(node_output, dict) else None
            )

            final_data = {
                "markdown_report": final_report_markdown,
                "map_html": map_html_content
            }
            yield f"event: final_report\ndata: {json.dumps(final_data)}\n\n"

        except Exception as e:
            run_status = "error"
            run_error = str(e)
            print(f"AN ERROR OCCURRED during stream: {e}")
            error_message = f"An error occurred: {e}"
            yield f"event: error\ndata: {json.dumps({'message': error_message})}\n\n"
        finally:
            try:
                persist_run(db, telemetry, status=run_status, error=run_error, route="plan")
            except Exception as persist_exc:
                print(f"-> Failed to persist agent run: {persist_exc}")
            db.close()

    return StreamingResponse(event_stream(), media_type="text/event-stream")
