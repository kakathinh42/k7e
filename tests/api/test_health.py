"""Tests for /healthz and /metrics endpoints (Task 3.1)."""

from fastapi.testclient import TestClient
from k7e_api.main import app

client = TestClient(app)


def test_healthz_ok():
    """GET /healthz returns 200 and JSON {"status": "ok"}."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_metrics_endpoint():
    """GET /metrics returns 200, content-type text/plain, body contains wiki_ingest_total."""
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "wiki_ingest_total" in response.text
