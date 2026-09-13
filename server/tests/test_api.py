"""Smoke test tầng API: đủ route và các endpoint công khai trả lời được.

Không đụng tới Postgres — chỉ dùng các route không cần DB.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app

ROUTE_MONG_DOI = {
    ("GET", "/"),
    ("GET", "/health"),
    ("GET", "/metrics"),  # Prometheus Instrumentator
    ("POST", "/auth/register"),
    ("POST", "/auth/login"),
    ("GET", "/auth/me"),
    ("GET", "/chats"),
    ("GET", "/chats/{session_id}"),
    ("PUT", "/chats/{session_id}"),
    ("DELETE", "/chats/{session_id}"),
    ("GET", "/metrics/agents"),
    ("GET", "/metrics/runs/{run_id}"),
    ("POST", "/chat-stream"),
    ("POST", "/plan-trip-stream"),
}


def test_du_route():
    spec = app.openapi()
    thuc_te = {
        (method.upper(), path)
        for path, ops in spec["paths"].items()
        for method in ops
    }
    assert thuc_te == ROUTE_MONG_DOI


@pytest.fixture
def client():
    # Bỏ qua lifespan vì nó gọi init_db() và cần Postgres.
    return TestClient(app)


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "running" in response.json()["status"]


def test_route_can_dang_nhap_thi_tu_choi(client):
    assert client.get("/chats").status_code == 401
    assert client.get("/metrics/agents").status_code == 401
