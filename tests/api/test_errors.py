from fastapi.testclient import TestClient
from k7e_api.main import app


def test_unhandled_exception_returns_error_envelope():
    @app.get("/_boom_test")
    def boom():
        raise RuntimeError("kaboom")

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/_boom_test")
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "internal_error"
    assert "message" in body["error"]
