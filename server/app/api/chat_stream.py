"""Hai endpoint SSE: hoi thoai co giam sat va lap ke hoach mot lan."""
import asyncio
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.sse import sse, status_for_node
from app.core.config import MOCK_MODE
from app.core.security import get_current_user
from app.core.telemetry import bind_run, persist_run, start_run
from app.db.models import User
from app.db.session import SessionLocal
from app.domain.conversation import (
    build_graph_state,
    determine_refresh,
    slots_snapshot,
    summarize_completed_plan,
    synthesize_user_request,
)
from app.domain.planning_issues import collect_planning_issues
from app.graph.builder import app as travel_agent_app
from app.graph.supervisor import after_plan_complete, run_supervised_turn
from app.memory.working import get_or_create_session
from app.schemas import ChatRequest

router = APIRouter(tags=["chat"])


class PlanRequest(BaseModel):
    user_query: str


@router.post("/chat-stream")
async def chat_stream(request: ChatRequest, user: User = Depends(get_current_user)):
    if MOCK_MODE:
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
        try:# Lấy hoặc tạo ra session đoạn chat
            session = get_or_create_session(db, user.id, request.session_id)
            yield sse("session", {"session_id": session.session_id})
            telemetry = start_run(user.id, session.session_id, kind="chat")

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
            initial_state["session_id"] = session.session_id
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
            issues = collect_planning_issues(full_state, language) if not session.has_plan else []
            if issues:
                run_status = "incomplete"
                run_error = " ".join(issues)

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
                    "success": session.has_plan,
                    "issues": issues,
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


@router.post("/plan-trip-stream")
async def plan_trip_stream(request: PlanRequest, user: User = Depends(get_current_user)):

    if MOCK_MODE:
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
        initial_state["session_id"] = telemetry.id
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
                "map_html": map_html_content,
                "success": bool(full_state.get("final_itinerary") and final_report_markdown),
                "issues": collect_planning_issues(full_state),
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
