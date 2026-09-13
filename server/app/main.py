"""Diem vao cua orchestrator: tao FastAPI app va gan cac router."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from app.api import auth, chats, chat_stream, metrics
from app.db.session import init_db


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="AI Travel Agent API",
    description="An API to generate travel itineraries using a multi-agent system.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Instrumentator().instrument(app).expose(app)

app.include_router(auth.router)
app.include_router(chats.router)
app.include_router(metrics.router)
app.include_router(chat_stream.router)


@app.get("/")
def read_root():
    return {"status": "AI Travel Agent API is running."}


@app.get("/health")
def health():
    return {"ok": True}
