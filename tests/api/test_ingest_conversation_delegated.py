"""Task 4: get_effective_principal wired on POST /ingest/conversation.

A delegation-allowed ClientApp (X-App-Key) may push a conversation as the
end user it asserts via X-On-Behalf-Of-Email — the thread lands in that
user's personal Space (or team Space, gated by Membership), exactly like a
direct end-user call would. Any other caller (no app key) still gets the
header ignored — no impersonation.

Modeled on tests/api/test_ingest_conversation.py (same client/fixture setup).
"""

from __future__ import annotations

import k7e_api.deps as deps_module
from k7e_api.app_auth import generate_app_key
from k7e_api.models import ClientApp, Membership, Organization, RawDocument, Space
from k7e_api.teams import provision_team
from sqlalchemy import select

from tests.api.conftest import TEST_TENANT_CONTEXT

_ORG = TEST_TENANT_CONTEXT.org_id


class _FakeStore:
    def put(self, key, data):
        return f"mem://{key}"


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


def _seed_delegation_app(sqlite_factory, *, domain: str | None = None) -> str:
    """Seed a delegation-allowed ClientApp in the test org; return the plaintext key.

    The app's org_id MUST match TEST_TENANT_CONTEXT.org_id (api_client
    overrides get_tenant_context to that fixed ctx) so the F4 org-binding
    guard in get_effective_principal admits the delegation.
    """
    with sqlite_factory() as s:
        org = s.get(Organization, _ORG)
        if org is None:
            s.add(Organization(id=_ORG, slug="test-org", name="Test Org"))
            s.flush()
        plaintext, key_hash = generate_app_key()
        s.add(
            ClientApp(
                org_id=_ORG,
                slug="chat-agent",
                name="Chat Agent",
                api_key_hash=key_hash,
                can_delegate_identity=True,
                allowed_identity_domain=domain,
            )
        )
        s.commit()
        return plaintext


_CONV_BODY = {
    "source_external_id": "thread-d1",
    "content": "alice: how do points expire?\nbob: after 12 months",
    "participants": ["alice", "bob"],
    "captured_at": "2026-07-09T12:00:00+00:00",
}


def test_delegated_conversation_lands_in_users_personal_space(
    api_client, sqlite_factory, monkeypatch
):
    _fakes(api_client, monkeypatch)
    key = _seed_delegation_app(sqlite_factory)
    resp = api_client.post(
        "/ingest/conversation",
        json=_CONV_BODY,
        headers={"X-App-Key": key, "X-On-Behalf-Of-Email": "alice@example.com"},
    )
    assert resp.status_code == 200, resp.text
    with sqlite_factory() as s:
        raw = s.execute(select(RawDocument)).scalars().one()
        assert raw.created_by == "alice@example.com"
        assert raw.allowed_groups == ["user:alice@example.com"]
        sp = s.get(Space, raw.space_id)
        assert sp is not None
        assert sp.owner_user_id == "alice@example.com"


def test_on_behalf_header_ignored_without_delegation_app(api_client, sqlite_factory, monkeypatch):
    _fakes(api_client, monkeypatch)
    resp = api_client.post(
        "/ingest/conversation",
        json=_CONV_BODY,
        headers={"X-On-Behalf-Of-Email": "alice@example.com"},
    )
    assert resp.status_code == 200, resp.text
    with sqlite_factory() as s:
        raw = s.execute(select(RawDocument)).scalars().one()
        assert raw.created_by != "alice@example.com"  # impersonation did not happen


def test_delegated_team_member_ingests(api_client, sqlite_factory, monkeypatch):
    _fakes(api_client, monkeypatch)
    key = _seed_delegation_app(sqlite_factory)
    with sqlite_factory() as s:
        team = provision_team(s, slug="eng", name="Eng", owner_id="owner-x", org_id=_ORG)
        s.add(Membership(team_id=team.id, user_id="alice@example.com", role="member"))
        s.commit()

    resp = api_client.post(
        "/ingest/conversation",
        json={**_CONV_BODY, "team": "eng"},
        headers={"X-App-Key": key, "X-On-Behalf-Of-Email": "alice@example.com"},
    )
    assert resp.status_code == 200, resp.text
    with sqlite_factory() as s:
        raw = s.execute(select(RawDocument)).scalars().one()
        assert raw.allowed_groups == ["team:eng"]
        assert raw.created_by == "alice@example.com"


def test_delegated_non_member_403(api_client, sqlite_factory, monkeypatch):
    _fakes(api_client, monkeypatch)
    key = _seed_delegation_app(sqlite_factory)
    with sqlite_factory() as s:
        provision_team(s, slug="eng", name="Eng", owner_id="owner-x", org_id=_ORG)
        s.commit()

    resp = api_client.post(
        "/ingest/conversation",
        json={**_CONV_BODY, "team": "eng"},
        headers={"X-App-Key": key, "X-On-Behalf-Of-Email": "alice@example.com"},
    )
    assert resp.status_code == 403, resp.text
    with sqlite_factory() as s:
        assert s.execute(select(RawDocument)).scalars().first() is None
