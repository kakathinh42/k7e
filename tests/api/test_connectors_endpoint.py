"""M5: POST /connectors/{space_slug}/sync — admin-gated connector run."""

from __future__ import annotations

import k7e_api.deps as deps_module
import k7e_api.routers.connectors as connectors_router
from k7e_api.auth import get_authz
from k7e_api.config import Settings, get_settings
from k7e_api.connectors.base import FetchedDocument
from k7e_api.main import app
from k7e_api.models import RawDocument, Space

from tests.api.conftest import TEST_TENANT_CONTEXT


class _FakeAuthz:
    def __init__(self, admin):
        self._admin = admin

    def can_admin(self, principal, scope):
        return self._admin

    def allowed_item_ids(self, principal, session):  # unused here
        return None


class _FakeStore:
    def put(self, key, data):
        return f"mem://{key}"


class _FakeConn:
    name = "confluence"

    def fetch(self):
        yield FetchedDocument(
            source_system="confluence",
            source_external_id="1",
            source_tier="A",
            filename="a.html",
            content=b"<p>a</p>",
            content_type="text/html",
        )


CONFIG = {
    "type": "confluence",
    "base_url": "https://x/wiki",
    "space_key": "RCVN",
    "defaults": {"allowed_groups": ["g1"]},
}


def _seed_space(sqlite_factory, *, slug="rcvn", config):
    with sqlite_factory() as s:
        s.add(
            Space(
                slug=slug,
                name=slug,
                org_id=TEST_TENANT_CONTEXT.org_id,
                connector_config=config,
            )
        )
        s.commit()


def test_non_admin_gets_403(api_client, sqlite_factory, monkeypatch):
    _seed_space(sqlite_factory, config=CONFIG)
    monkeypatch.setitem(app.dependency_overrides, get_authz, lambda: _FakeAuthz(False))
    assert api_client.post("/connectors/rcvn/sync").status_code == 403


def test_missing_space_404(api_client, sqlite_factory, monkeypatch):
    monkeypatch.setitem(app.dependency_overrides, get_authz, lambda: _FakeAuthz(True))
    assert api_client.post("/connectors/nope/sync").status_code == 404


def test_space_without_config_400(api_client, sqlite_factory, monkeypatch):
    _seed_space(sqlite_factory, config=None)
    monkeypatch.setitem(app.dependency_overrides, get_authz, lambda: _FakeAuthz(True))
    assert api_client.post("/connectors/rcvn/sync").status_code == 400


def test_missing_token_500(api_client, sqlite_factory, monkeypatch):
    # Force blank creds so build_connector raises RuntimeError -> 500, regardless
    # of any ambient CONFLUENCE_* env vars in the shell.
    _seed_space(sqlite_factory, config=CONFIG)
    monkeypatch.setitem(app.dependency_overrides, get_authz, lambda: _FakeAuthz(True))
    monkeypatch.setitem(
        app.dependency_overrides,
        get_settings,
        lambda: Settings(confluence_api_token="", confluence_user_email=""),
    )
    assert api_client.post("/connectors/rcvn/sync").status_code == 500


def test_admin_runs_connector_and_stamps_tenant(api_client, sqlite_factory, monkeypatch):
    _seed_space(sqlite_factory, config=CONFIG)
    monkeypatch.setitem(app.dependency_overrides, get_authz, lambda: _FakeAuthz(True))
    monkeypatch.setitem(
        app.dependency_overrides, deps_module.get_object_store, lambda: _FakeStore()
    )
    monkeypatch.setitem(
        app.dependency_overrides,
        deps_module.get_workflow_starter,
        lambda: lambda rid: "wf",
    )
    monkeypatch.setattr(connectors_router, "build_connector", lambda space, settings: _FakeConn())

    resp = api_client.post("/connectors/rcvn/sync")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"connector": "confluence", "ingested": 1, "skipped": 0}

    with sqlite_factory() as s:
        from sqlalchemy import select

        row = s.execute(select(RawDocument)).scalars().one()
        assert row.org_id == TEST_TENANT_CONTEXT.org_id
        assert row.allowed_groups == ["g1"]


def test_async_workflow_starter_is_awaited(api_client, sqlite_factory, monkeypatch):
    # Regression: production start_ingest_workflow is ASYNC. The sync route must
    # adapt it (asyncio.run) — passing an un-awaited coroutine to ingest_document
    # would raise and leave the IngestWorkflow unstarted. Without the adapter this
    # 500s; with it, the async starter is actually run.
    _seed_space(sqlite_factory, config=CONFIG)
    started = []

    async def _async_start(raw_id):
        started.append(raw_id)
        return "wf-async"

    monkeypatch.setitem(app.dependency_overrides, get_authz, lambda: _FakeAuthz(True))
    monkeypatch.setitem(
        app.dependency_overrides, deps_module.get_object_store, lambda: _FakeStore()
    )
    monkeypatch.setitem(
        app.dependency_overrides, deps_module.get_workflow_starter, lambda: _async_start
    )
    monkeypatch.setattr(connectors_router, "build_connector", lambda space, settings: _FakeConn())

    resp = api_client.post("/connectors/rcvn/sync")
    assert resp.status_code == 200, resp.text
    assert resp.json()["ingested"] == 1
    assert len(started) == 1  # the async starter was actually run (awaited)
