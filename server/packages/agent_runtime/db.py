from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager, contextmanager
from typing import Iterator, Optional

from dotenv import load_dotenv
from pgvector.psycopg2 import register_vector
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import AgentRuntimeBase

load_dotenv()

_engine: Optional[Engine] = None
_SessionLocal = None


def _register_vector(dbapi_connection, _connection_record):
    try:
        register_vector(dbapi_connection)
    except Exception:
        pass


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        url = os.getenv(
            "DATABASE_URL",
            "postgresql://travel:travel@localhost:5432/travel_agent",
        )
        _engine = create_engine(url, pool_pre_ping=True)
        event.listen(_engine, "connect", _register_vector)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _engine


def get_session_factory():
    get_engine()
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()


# Cot moi them vao bang DA TON TAI. metadata.create_all KHONG alter bang da co, nen
# phai dung ALTER ... IF NOT EXISTS (idempotent, chay lai moi lan khoi dong cung duoc).
# Giu danh sach nay dong bo voi app/db/session.py.
_LIGHT_MIGRATIONS = (
    ("agent_facts", "destination", "VARCHAR(160)"),
    ("agent_facts", "embed_model", "VARCHAR(120)"),
    ("user_facts", "embed_model", "VARCHAR(120)"),
    ("episodes", "embed_model", "VARCHAR(120)"),
)


def apply_light_migrations(connection) -> None:
    """Them cot moi cho bang da ton tai. Nhan mot connection da mo.

    Bo qua bang chua ton tai: agent-service chi tao 3 bang agent_*, con user_facts /
    episodes do orchestrator tao. Neu service khoi dong truoc orchestrator tren DB
    moi thi ALTER se loi, nen phai kiem tra truoc.
    """
    for table, column, ddl_type in _LIGHT_MIGRATIONS:
        exists = connection.execute(
            text("SELECT to_regclass(:name)"), {"name": table}
        ).scalar()
        if not exists:
            continue
        connection.execute(
            text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl_type}")
        )


def init_agent_db(retries: int = 30, delay: float = 1.0) -> None:
    """Create pgvector extension + agent_facts / agent_working / agent_cache."""
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            engine = get_engine()
            with engine.connect() as connection:
                connection = connection.execution_options(isolation_level="AUTOCOMMIT")
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            engine.dispose()
            AgentRuntimeBase.metadata.create_all(bind=engine)
            with engine.connect() as connection:
                connection = connection.execution_options(isolation_level="AUTOCOMMIT")
                apply_light_migrations(connection)
            print("-> Agent runtime tables ready (agent_facts, agent_working, agent_cache)")
            return
        except Exception as exc:
            last_error = exc
            print(f"-> Waiting for database ({attempt}/{retries}): {exc}")
            time.sleep(delay)
    raise RuntimeError(f"Could not initialize agent runtime tables: {last_error}") from last_error


@asynccontextmanager
async def agent_service_lifespan(_app):
    """FastAPI lifespan: create_all domain tables when DATABASE_URL is set."""
    if os.getenv("DATABASE_URL"):
        init_agent_db()
    yield
