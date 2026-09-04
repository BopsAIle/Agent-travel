from __future__ import annotations

import os
import time
from contextlib import contextmanager
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
            print("-> Agent runtime tables ready")
            return
        except Exception as exc:
            last_error = exc
            print(f"-> Waiting for database ({attempt}/{retries}): {exc}")
            time.sleep(delay)
    raise RuntimeError(f"Could not initialize agent runtime tables: {last_error}") from last_error
