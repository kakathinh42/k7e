from fastapi import FastAPI
from fastapi.testclient import TestClient
from k7e_api.main import app
from k7e_api.middleware import PrometheusMiddleware
from prometheus_client import REGISTRY


def test_request_metrics_recorded():
    client = TestClient(app)
    client.get("/healthz")
    count = REGISTRY.get_sample_value(
        "wiki_http_requests_total",
        {"method": "GET", "endpoint": "/healthz", "status": "200"},
    )
    assert count is not None and count >= 1


def test_request_metrics_recorded_on_5xx():
    """Metrics must still be recorded when a route raises an unhandled exception."""
    error_app = FastAPI()
    error_app.add_middleware(PrometheusMiddleware)

    @error_app.get("/boom")
    async def boom():
        raise RuntimeError("intentional server error")

    client = TestClient(error_app, raise_server_exceptions=False)
    client.get("/boom")

    count = REGISTRY.get_sample_value(
        "wiki_http_requests_total",
        {"method": "GET", "endpoint": "/boom", "status": "500"},
    )
    assert count is not None and count >= 1
