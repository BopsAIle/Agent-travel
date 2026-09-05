import os
import time

from dotenv import load_dotenv
from pgvector.psycopg2 import register_vector
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from db.base import Base

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://travel:travel@localhost:5432/travel_agent",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@event.listens_for(engine, "connect")
def _register_vector(dbapi_connection, _connection_record):
    try:
        register_vector(dbapi_connection)
    except Exception:
        pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


_AGENT_TABLES = ("agent_facts", "agent_working", "agent_cache")


def _assert_agent_table_schemas_match() -> None:
    """Fail fast if orchestrator and agent_runtime copies of the 3 tables drift."""
    from db.models import AgentCache, AgentFact, AgentWorking
    from packages.agent_runtime.models import AgentCache as RuntimeCache
    from packages.agent_runtime.models import AgentFact as RuntimeFact
    from packages.agent_runtime.models import AgentWorking as RuntimeWorking

    pairs = (
        (AgentFact, RuntimeFact),
        (AgentWorking, RuntimeWorking),
        (AgentCache, RuntimeCache),
    )
    for orchestrator_model, runtime_model in pairs:
        if orchestrator_model.__tablename__ != runtime_model.__tablename__:
            raise RuntimeError(
                f"Agent table name mismatch: {orchestrator_model.__tablename__} vs "
                f"{runtime_model.__tablename__}"
            )
        left = {column.name for column in orchestrator_model.__table__.columns}
        right = {column.name for column in runtime_model.__table__.columns}
        if left != right:
            raise RuntimeError(
                f"Schema drift on {orchestrator_model.__tablename__}: "
                f"orchestrator={sorted(left)} runtime={sorted(right)}"
            )


def init_db(retries: int = 30, delay: float = 1.0) -> None:
    import db.models  # noqa: F401 — traveler tables + agent_facts/working/cache

    _assert_agent_table_schemas_match()

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with engine.connect() as connection:
                connection = connection.execution_options(isolation_level="AUTOCOMMIT")
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            engine.dispose()
            Base.metadata.create_all(bind=engine)
            from packages.agent_runtime.models import AgentRuntimeBase

            AgentRuntimeBase.metadata.create_all(bind=engine)
            print(f"-> Database ready (includes {', '.join(_AGENT_TABLES)})")
            return
        except Exception as exc:
            last_error = exc
            print(f"-> Waiting for database ({attempt}/{retries}): {exc}")
            time.sleep(delay)
    raise RuntimeError(f"Could not initialize database: {last_error}") from last_error


def db_session() -> Session:
    return SessionLocal()
