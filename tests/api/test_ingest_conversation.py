"""M3 Step C: POST /ingest/conversation — team-gated Tier-B conversation ingest.

Task 8 extends this: ``team`` is optional — absent, the thread lands in the
caller's own personal Space (same JIT-provisioning + daily cap as upload's
``space=personal`` alias from Task 7), gated purely by verified identity (no
``can_write`` check — owner-by-construction, mirrors the Task 7 upload fix).
"""

from __future__ import annotations

import k7e_api.deps as deps_module
from k7e_api.config import get_settings
from k7e_api.models import Organization, RawDocument, Space
from k7e_api.teams import provision_team
from sqlalchemy import select

from tests.api.conftest import TEST_TENANT_CONTEXT

_ORG = TEST_TENANT_CONTEXT.org_id


class _FakeStore:
    def put(self, key, data):
        return f"mem://{key}"


def _seed_team(sqlite_factory):
    with sqlite_factory() as s:
        s.add(Organization(id=_ORG, slug="test-org", name="Test Org"))
        s.flush()
        provision_team(s, slug="eng", name="Eng", owner_id="alice", org_id=_ORG)
        s.commit()


def _fakes(api_client, monkeypatch):
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


_BODY = {
    "team": "eng",
    "source_external_id": "thread-1",
    "content": "alice: how do points expire?\nbob: after 12 months",
    "participants": ["alice", "bob"],
    "captured_at": "2026-07-06T12:00:00+00:00",
}

# Same shape, no team — Task 8's personal-fallback path.
_BODY_NO_TEAM = {k: v for k, v in _BODY.items() if k != "team"}


def test_member_ingests_conversation(api_client, sqlite_factory, monkeypatch):
    _seed_team(sqlite_factory)
    _fakes(api_client, monkeypatch)
    r = api_client.post("/ingest/conversation", json=_BODY, headers={"X-User-Id": "alice"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["idempotent"] is False
    assert body["raw_document_id"]
    with sqlite_factory() as s:
        row = s.execute(select(RawDocument)).scalars().one()
        assert row.source_system == "chat_agent"
        assert row.source_tier == "B"
        assert row.allowed_groups == ["team:eng"]
        assert row.org_id == _ORG
        assert row.extra_metadata["participants"] == ["alice", "bob"]
        assert row.extra_metadata["captured_at"] == "2026-07-06T12:00:00+00:00"


def test_non_member_403(api_client, sqlite_factory, monkeypatch):
    _seed_team(sqlite_factory)
    _fakes(api_client, monkeypatch)
    r = api_client.post("/ingest/conversation", json=_BODY, headers={"X-User-Id": "carol"})
    assert r.status_code == 403, r.text
    with sqlite_factory() as s:
        assert s.execute(select(RawDocument)).scalars().first() is None


def test_no_identity_403(api_client, sqlite_factory, monkeypatch):
    _seed_team(sqlite_factory)
    _fakes(api_client, monkeypatch)
    r = api_client.post("/ingest/conversation", json=_BODY)
    assert r.status_code == 403, r.text


def test_unknown_team_404(api_client, sqlite_factory, monkeypatch):
    _seed_team(sqlite_factory)
    _fakes(api_client, monkeypatch)
    bad = {**_BODY, "team": "nope"}
    r = api_client.post("/ingest/conversation", json=bad, headers={"X-User-Id": "alice"})
    assert r.status_code == 404, r.text


def test_empty_content_422(api_client, sqlite_factory, monkeypatch):
    _seed_team(sqlite_factory)
    _fakes(api_client, monkeypatch)
    bad = {**_BODY, "content": ""}
    r = api_client.post("/ingest/conversation", json=bad, headers={"X-User-Id": "alice"})
    assert r.status_code == 422, r.text


def test_idempotent_repost(api_client, sqlite_factory, monkeypatch):
    _seed_team(sqlite_factory)
    _fakes(api_client, monkeypatch)
    r1 = api_client.post("/ingest/conversation", json=_BODY, headers={"X-User-Id": "alice"})
    r2 = api_client.post("/ingest/conversation", json=_BODY, headers={"X-User-Id": "alice"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["idempotent"] is True
    assert r2.json()["raw_document_id"] == r1.json()["raw_document_id"]
    with sqlite_factory() as s:
        assert len(s.execute(select(RawDocument)).scalars().all()) == 1


def test_overlong_external_id_422(api_client, sqlite_factory, monkeypatch):
    _seed_team(sqlite_factory)
    _fakes(api_client, monkeypatch)
    bad = {**_BODY, "source_external_id": "x" * 300}
    r = api_client.post("/ingest/conversation", json=bad, headers={"X-User-Id": "alice"})
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# Task 8: `team` optional -> personal-space fallback.
# ---------------------------------------------------------------------------


def test_no_team_lands_in_personal_space(api_client, sqlite_factory, monkeypatch):
    _fakes(api_client, monkeypatch)
    r = api_client.post("/ingest/conversation", json=_BODY_NO_TEAM, headers={"X-User-Id": "alice"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["idempotent"] is False
    assert body["raw_document_id"]
    with sqlite_factory() as s:
        row = s.execute(select(RawDocument)).scalars().one()
        assert row.source_system == "chat_agent"
        assert row.allowed_groups == ["user:alice"]
        assert row.space_id is not None
        assert row.created_by == "alice"
        space = s.get(Space, row.space_id)
        assert space is not None
        assert space.owner_user_id == "alice"


def test_no_team_cap_enforced_team_push_uncapped(api_client, sqlite_factory, monkeypatch):
    _seed_team(sqlite_factory)
    _fakes(api_client, monkeypatch)
    monkeypatch.setenv("PERSONAL_INGEST_DAILY_CAP", "1")
    get_settings.cache_clear()
    try:
        first = {**_BODY_NO_TEAM, "source_external_id": "thread-p1"}
        r1 = api_client.post("/ingest/conversation", json=first, headers={"X-User-Id": "alice"})
        assert r1.status_code == 200, r1.text

        second = {**_BODY_NO_TEAM, "source_external_id": "thread-p2"}
        r2 = api_client.post("/ingest/conversation", json=second, headers={"X-User-Id": "alice"})
        assert r2.status_code == 429, r2.text

        # A team push is not gated by the personal cap.
        r3 = api_client.post("/ingest/conversation", json=_BODY, headers={"X-User-Id": "alice"})
        assert r3.status_code == 200, r3.text
    finally:
        get_settings.cache_clear()


def test_no_team_idempotent_repost(api_client, sqlite_factory, monkeypatch):
    _fakes(api_client, monkeypatch)
    r1 = api_client.post(
        "/ingest/conversation", json=_BODY_NO_TEAM, headers={"X-User-Id": "alice"}
    )
    r2 = api_client.post(
        "/ingest/conversation", json=_BODY_NO_TEAM, headers={"X-User-Id": "alice"}
    )
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert r2.json()["idempotent"] is True
    assert r2.json()["raw_document_id"] == r1.json()["raw_document_id"]
    with sqlite_factory() as s:
        assert len(s.execute(select(RawDocument)).scalars().all()) == 1
