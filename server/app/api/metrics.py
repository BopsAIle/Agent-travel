"""Doc so lieu telemetry cua cac agent run."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.metrics import agent_metrics_overview, agent_run_detail
from app.core.security import get_current_user
from app.db.models import User
from app.db.session import get_db

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/agents")
def metrics_agents(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return agent_metrics_overview(db, user.id)


@router.get("/runs/{run_id}")
def metrics_run(run_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        parsed = uuid.UUID(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Run not found.") from exc
    detail = agent_run_detail(db, user.id, parsed)
    if not detail:
        raise HTTPException(status_code=404, detail="Run not found.")
    return detail
