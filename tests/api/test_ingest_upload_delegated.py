"""get_effective_principal wired on POST /ingest/upload.

A delegation-allowed ClientApp (X-App-Key) may upload a document as the end
user it asserts via X-On-Behalf-Of-Email — with space=personal the file lands
in that user's personal Space, exactly like a direct end-user call. Any other
caller gets the header ignored — no impersonation.

Modeled on tests/api/test_ingest_conversation_delegated.py.
"""

from __future__ import annotations

import k7e_api.deps as deps_module
from k7e_api.app_auth import generate_app_key
from k7e_api.models import ClientApp, Organization, RawDocument, Space
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


def _upload(api_client, *, headers=None, space="personal"):
    return api_client.post(
        "/ingest/upload",
        files={"file": ("note.md", b"# hello\n", "text/markdown")},
        data={"space": space},
        headers=headers or {},
    )


def test_delegated_upload_lands_in_users_personal_space(api_client, sqlite_factory, monkeypatch):
    _fakes(api_client, monkeypatch)
    key = _seed_delegation_app(sqlite_factory)
    resp = _upload(
        api_client,
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
    resp = _upload(api_client, headers={"X-On-Behalf-Of-Email": "alice@example.com"})
    assert resp.status_code == 200, resp.text
    with sqlite_factory() as s:
        raw = s.execute(select(RawDocument)).scalars().one()
        assert raw.created_by != "alice@example.com"  # impersonation did not happen


def test_delegated_upload_malformed_email_400(api_client, sqlite_factory, monkeypatch):
    _fakes(api_client, monkeypatch)
    key = _seed_delegation_app(sqlite_factory)
    resp = _upload(
        api_client,
        headers={"X-App-Key": key, "X-On-Behalf-Of-Email": "not-an-email"},
    )
    assert resp.status_code == 400, resp.text
    with sqlite_factory() as s:
        assert s.execute(select(RawDocument)).scalars().first() is None


def test_delegated_upload_domain_guard_403(api_client, sqlite_factory, monkeypatch):
    _fakes(api_client, monkeypatch)
    key = _seed_delegation_app(sqlite_factory, domain="example.com")
    resp = _upload(
        api_client,
        headers={"X-App-Key": key, "X-On-Behalf-Of-Email": "eve@evil.com"},
    )
    assert resp.status_code == 403, resp.text
    with sqlite_factory() as s:
        assert s.execute(select(RawDocument)).scalars().first() is None
