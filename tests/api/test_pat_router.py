"""PAT create/list/revoke endpoints (PAT SSO Phase 1, Task 4)."""

from __future__ import annotations

import pytest
from k7e_api.config import get_settings
from k7e_api.models import PersonalAccessToken
from k7e_api.pat_auth import hash_pat
from k7e_api.session_auth import mint_session
from sqlalchemy import select


@pytest.fixture()
def client(api_client, monkeypatch):
    """api_client with self-issued-session auth enabled (jwt_enabled + secret)."""
    monkeypatch.setenv("JWT_ENABLED", "true")
    monkeypatch.setenv("SESSION_SIGNING_SECRET", "test-secret")
    monkeypatch.setenv("SESSION_ISSUER", "k7e-session")
    # non-dev env so a no-Bearer call resolves to anonymous (fail-closed), which
    # lets the "requires auth" case assert a 401 rather than the dev fallback.
    monkeypatch.setenv("ENV", "prod")
    get_settings.cache_clear()
    yield api_client
    get_settings.cache_clear()


def _auth(email: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_session(email, get_settings())}"}


def test_create_pat_returns_plaintext_once_and_stores_only_hash(client, sqlite_factory):
    r = client.post("/pat", json={"name": "laptop"}, headers=_auth("alice@example.com"))
    assert r.status_code == 200, r.text
    body = r.json()
    token = body["token"]
    assert token.startswith("wpat_")
    assert body["name"] == "laptop"
    with sqlite_factory() as s:
        row = s.execute(select(PersonalAccessToken)).scalar_one()
        assert row.user_id == "alice@example.com"
        assert row.token_hash == hash_pat(token)  # only the hash is stored
        assert token not in (row.token_hash, row.name)


def test_list_pat_hides_plaintext_and_scopes_to_caller(client, sqlite_factory):
    client.post("/pat", json={"name": "a"}, headers=_auth("alice@example.com"))
    client.post("/pat", json={"name": "b"}, headers=_auth("bob@example.com"))
    r = client.get("/pat", headers=_auth("alice@example.com"))
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) == 1  # only alice's
    assert items[0]["name"] == "a"
    assert "token" not in items[0] and "token_hash" not in items[0]


def test_revoke_pat_sets_revoked_and_is_owner_scoped(client, sqlite_factory):
    created = client.post("/pat", json={"name": "a"}, headers=_auth("alice@example.com")).json()
    pat_id = created["id"]
    # bob cannot revoke alice's token
    assert client.delete(f"/pat/{pat_id}", headers=_auth("bob@example.com")).status_code == 404
    # alice can
    assert client.delete(f"/pat/{pat_id}", headers=_auth("alice@example.com")).status_code == 204
    with sqlite_factory() as s:
        row = s.execute(select(PersonalAccessToken)).scalar_one()
        assert row.revoked_at is not None


def test_create_pat_requires_auth(client):
    # no Authorization → not a verified user → 401
    assert client.post("/pat", json={"name": "x"}).status_code == 401


def test_create_pat_rejects_bad_input_with_422_not_500(client):
    h = _auth("alice@example.com")
    # absurd expiry must be a clean 422, not an OverflowError 500
    assert (
        client.post(
            "/pat", json={"name": "x", "expires_days": 999999999999}, headers=h
        ).status_code
        == 422
    )
    # over-long name must be a clean 422, not a DB DataError 500
    assert client.post("/pat", json={"name": "z" * 300}, headers=h).status_code == 422
