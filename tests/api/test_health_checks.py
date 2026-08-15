import k7e_api.health as health


async def test_readiness_all_ok(monkeypatch):
    monkeypatch.setattr(health, "check_db", lambda: True)

    async def fake_temporal():
        return True

    monkeypatch.setattr(health, "check_temporal", fake_temporal)
    monkeypatch.setattr(health, "check_object_store", lambda: True)

    ready, checks = await health.readiness()
    assert ready is True
    assert checks == {"db": "ok", "temporal": "ok", "object_store": "ok"}


async def test_readiness_reports_failure(monkeypatch):
    monkeypatch.setattr(health, "check_db", lambda: False)

    async def fake_temporal():
        return True

    monkeypatch.setattr(health, "check_temporal", fake_temporal)
    monkeypatch.setattr(health, "check_object_store", lambda: True)

    ready, checks = await health.readiness()
    assert ready is False
    assert checks["db"] == "error"
