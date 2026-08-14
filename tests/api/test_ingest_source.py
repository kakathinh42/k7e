"""M6: POST /ingest/source — a registered app ingests a source as itself."""

from __future__ import annotations

import k7e_api.deps as deps_module
from k7e_api.app_auth import generate_app_key
from k7e_api.auth import get_authz
from k7e_api.models import ClientApp, RoleGrant
from k7e_api.rbac import HierarchicalRbacAuthorizationService

from tests.api.conftest import TEST_TENANT_CONTEXT


class _FakeStore:
    def put(self, key, data):
        return f"mem://{key}"


def _seed_app(sqlite_factory, *, with_grant=True):
    plaintext, key_hash = generate_app_key()
    with sqlite_factory() as s:
        s.add(
            ClientApp(
                org_id=TEST_TENANT_CONTEXT.org_id,
                slug="chat-agent",
                name="Chat Agent",
                api_key_hash=key_hash,
            )
        )
        if with_grant:
            s.add(
                RoleGrant(
                    principal_kind="app",
                    principal_id="chat-agent",
                    role="editor",
                    scope_kind="org",
                    scope_id=TEST_TENANT_CONTEXT.org_id,
                )
            )
        s.commit()
    return plaintext


_BODY = {
    "source_system": "chat_agent",
    "source_external_id": "conv-1",
    "source_tier": "B",
    "content": "user asked about points expiry",
    "content_type": "text/markdown",
}


def _fakes(api_client, monkeypatch, sqlite_factory):
    monkeypatch.setitem(
        api_client.app.dependency_overrides,
        deps_module.get_object_store,
        lambda: _FakeStore(),
    )
    monkeypatch.setitem(
        api_client.app.dependency_overrides,
        deps_module.get_workflow_starter,
        lambda: lambda rid: "wf",
    )
    # The default get_authz() binds HierarchicalRbacAuthorizationService to the
    # production SessionLocal, which can't see this test's in-memory sqlite DB
    # (see test_rbac_write_gating.py / test_teams_api.py for the same fix) — so
    # the app's RoleGrant would otherwise be invisible and every write-gated
    # call would fail closed with 403.
    monkeypatch.setitem(
        api_client.app.dependency_overrides,
        get_authz,
        lambda: HierarchicalRbacAuthorizationService(session_factory=sqlite_factory),
    )


def test_app_ingests_source(api_client, sqlite_factory, monkeypatch):
    key = _seed_app(sqlite_factory)
    _fakes(api_client, monkeypatch, sqlite_factory)
    resp = api_client.post("/ingest/source", json=_BODY, headers={"X-App-Key": key})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ingested"
    assert resp.json()["raw_document_id"]

    from k7e_api.models import RawDocument
    from sqlalchemy import select

    with sqlite_factory() as s:
        row = s.execute(select(RawDocument)).scalars().one()
        assert row.org_id == TEST_TENANT_CONTEXT.org_id
        assert row.source_system == "chat_agent"


def test_missing_key_401(api_client, sqlite_factory):
    _seed_app(sqlite_factory)
    assert api_client.post("/ingest/source", json=_BODY).status_code == 401


def test_app_without_grant_403(api_client, sqlite_factory, monkeypatch):
    key = _seed_app(sqlite_factory, with_grant=False)
    _fakes(api_client, monkeypatch, sqlite_factory)
    assert (
        api_client.post("/ingest/source", json=_BODY, headers={"X-App-Key": key}).status_code
        == 403
    )


def test_empty_content_400(api_client, sqlite_factory, monkeypatch):
    key = _seed_app(sqlite_factory)
    _fakes(api_client, monkeypatch, sqlite_factory)
    bad = {**_BODY, "content": ""}
    assert (
        api_client.post("/ingest/source", json=bad, headers={"X-App-Key": key}).status_code == 400
    )


def test_invalid_source_tier_400(api_client, sqlite_factory, monkeypatch):
    # An external caller supplying a bogus tier must get a clean 400, not a 500.
    key = _seed_app(sqlite_factory)
    _fakes(api_client, monkeypatch, sqlite_factory)
    bad = {**_BODY, "source_tier": "bogus"}
    assert (
        api_client.post("/ingest/source", json=bad, headers={"X-App-Key": key}).status_code == 400
    )


def test_idempotent_repost_skipped(api_client, sqlite_factory, monkeypatch):
    key = _seed_app(sqlite_factory)
    _fakes(api_client, monkeypatch, sqlite_factory)
    api_client.post("/ingest/source", json=_BODY, headers={"X-App-Key": key})
    resp2 = api_client.post("/ingest/source", json=_BODY, headers={"X-App-Key": key})
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "skipped"
