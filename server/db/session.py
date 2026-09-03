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


def init_db(retries: int = 30, delay: float = 1.0) -> None:
    import db.models  # noqa: F401 — register models on Base.metadata

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with engine.connect() as connection:
                connection = connection.execution_options(isolation_level="AUTOCOMMIT")
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            engine.dispose()
            Base.metadata.create_all(bind=engine)
            print("-> Database ready")
            return
        except Exception as exc:
            last_error = exc
            print(f"-> Waiting for database ({attempt}/{retries}): {exc}")
            time.sleep(delay)
    raise RuntimeError(f"Could not initialize database: {last_error}") from last_error


def db_session() -> Session:
    return SessionLocal()
