"""M6: POST/GET /apps — org-admin app provisioning (one-time key)."""

from __future__ import annotations

from k7e_api.app_auth import hash_app_key
from k7e_api.auth import get_authz
from k7e_api.models import ClientApp, RoleGrant


class _FakeAuthz:
    def __init__(self, admin):
        self._admin = admin

    def can_admin(self, principal, scope):
        return self._admin

    def allowed_item_ids(self, principal, session):
        return None


def test_provision_returns_one_time_key_and_seeds_grant(api_client, sqlite_factory, monkeypatch):
    monkeypatch.setitem(api_client.app.dependency_overrides, get_authz, lambda: _FakeAuthz(True))
    resp = api_client.post("/apps", json={"slug": "chat-agent", "name": "Chat Agent"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    key = body["api_key"]
    assert key.startswith("wapp_")

    with sqlite_factory() as s:
        app = s.query(ClientApp).filter_by(slug="chat-agent").one()
        assert app.api_key_hash == hash_app_key(key)  # only the hash stored
        grant = s.query(RoleGrant).filter_by(principal_kind="app", principal_id="chat-agent").one()
        assert grant.role == "editor" and grant.scope_kind == "org"


def test_list_apps_never_leaks_key(api_client, sqlite_factory, monkeypatch):
    monkeypatch.setitem(api_client.app.dependency_overrides, get_authz, lambda: _FakeAuthz(True))
    api_client.post("/apps", json={"slug": "a1", "name": "A1"})
    data = api_client.get("/apps").json()
    assert any(a["slug"] == "a1" for a in data)
    assert all("api_key" not in a and "api_key_hash" not in a for a in data)


def test_provision_requires_admin(api_client, sqlite_factory, monkeypatch):
    monkeypatch.setitem(api_client.app.dependency_overrides, get_authz, lambda: _FakeAuthz(False))
    assert api_client.post("/apps", json={"slug": "x", "name": "X"}).status_code == 403


def test_duplicate_slug_409(api_client, sqlite_factory, monkeypatch):
    monkeypatch.setitem(api_client.app.dependency_overrides, get_authz, lambda: _FakeAuthz(True))
    api_client.post("/apps", json={"slug": "dup", "name": "A"})
    assert api_client.post("/apps", json={"slug": "dup", "name": "B"}).status_code == 409
