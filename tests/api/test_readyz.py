import k7e_api.health as health
from fastapi.testclient import TestClient
from k7e_api.main import app


def _patch(monkeypatch, db, temporal, store):
    monkeypatch.setattr(health, "check_db", lambda: db)

    async def fake_temporal():
        return temporal

    monkeypatch.setattr(health, "check_temporal", fake_temporal)
    monkeypatch.setattr(health, "check_object_store", lambda: store)


def test_readyz_ok(monkeypatch):
    _patch(monkeypatch, True, True, True)
    resp = TestClient(app).get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


def test_readyz_503_when_dep_down(monkeypatch):
    _patch(monkeypatch, False, True, True)
    resp = TestClient(app).get("/readyz")
    assert resp.status_code == 503
    assert resp.json()["checks"]["db"] == "error"
