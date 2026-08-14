"""Native email+password register/login (PAT SSO Phase 1, Task 2)."""

from __future__ import annotations

import base64
import json

import pytest
from k7e_api.config import get_settings
from k7e_api.models import Organization, User
from sqlalchemy import select

from tests.api.conftest import TEST_TENANT_CONTEXT

_ORG = TEST_TENANT_CONTEXT.org_id


@pytest.fixture()
def client(api_client, monkeypatch):
    """api_client with a non-empty session-signing secret so mint_session works."""
    monkeypatch.setenv("SESSION_SIGNING_SECRET", "test-secret")
    get_settings.cache_clear()
    yield api_client
    get_settings.cache_clear()


def _seed_org(sqlite_factory) -> None:
    with sqlite_factory() as s:
        if s.get(Organization, _ORG) is None:
            s.add(Organization(id=_ORG, slug="default", name="Default"))
            s.commit()


def _sub(token: str) -> str:
    p = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))["sub"]


def test_register_then_login_roundtrip(client, sqlite_factory):
    _seed_org(sqlite_factory)
    r = client.post(
        "/auth/register",
        json={"email": "alice@example.com", "password": "hunter2secret"},
    )
    assert r.status_code == 200, r.text
    assert _sub(r.json()["session_token"]) == "alice@example.com"
    # the row exists and stores a bcrypt hash, not the plaintext
    with sqlite_factory() as s:
        u = s.execute(select(User).where(User.email == "alice@example.com")).scalar_one()
        assert u.password_hash != "hunter2secret"
        assert u.org_id == _ORG
    # login is case-insensitive on email, returns a session for the user
    r2 = client.post(
        "/auth/login",
        json={"email": "Alice@example.com", "password": "hunter2secret"},
    )
    assert r2.status_code == 200, r2.text
    assert _sub(r2.json()["session_token"]) == "alice@example.com"


def test_register_rejects_non_allowed_domain(client, sqlite_factory):
    _seed_org(sqlite_factory)
    r = client.post(
        "/auth/register",
        json={"email": "eve@evil.com", "password": "hunter2secret"},
    )
    assert r.status_code == 400, r.text
    with sqlite_factory() as s:
        assert s.execute(select(User)).scalars().first() is None


def test_register_rejects_short_password(client, sqlite_factory):
    _seed_org(sqlite_factory)
    r = client.post("/auth/register", json={"email": "bob@example.com", "password": "short"})
    assert r.status_code == 400, r.text


def test_register_duplicate_conflicts(client, sqlite_factory):
    _seed_org(sqlite_factory)
    body = {"email": "carol@example.com", "password": "hunter2secret"}
    assert client.post("/auth/register", json=body).status_code == 200
    assert client.post("/auth/register", json=body).status_code == 409


def test_login_wrong_password_401(client, sqlite_factory):
    _seed_org(sqlite_factory)
    client.post(
        "/auth/register",
        json={"email": "dan@example.com", "password": "hunter2secret"},
    )
    r = client.post("/auth/login", json={"email": "dan@example.com", "password": "wrongpassword"})
    assert r.status_code == 401, r.text


def test_login_unknown_user_401(client, sqlite_factory):
    _seed_org(sqlite_factory)
    r = client.post(
        "/auth/login", json={"email": "ghost@example.com", "password": "hunter2secret"}
    )
    assert r.status_code == 401, r.text


def test_register_rejects_overlong_password_with_400_not_500(client, sqlite_factory):
    # bcrypt (>=4.1) RAISES over 72 bytes; the endpoint must validate, not 500.
    _seed_org(sqlite_factory)
    r = client.post(
        "/auth/register",
        json={"email": "long@example.com", "password": "Z" * 100},
    )
    assert r.status_code == 400, r.text
    # multibyte: 40 chars but 80 bytes — must also be a clean 400, not 500.
    r2 = client.post(
        "/auth/register",
        json={"email": "multibyte@example.com", "password": "é" * 40},
    )
    assert r2.status_code == 400, r2.text


def test_register_rejects_empty_local_part(client, sqlite_factory):
    _seed_org(sqlite_factory)
    r = client.post("/auth/register", json={"email": "@example.com", "password": "hunter2secret"})
    assert r.status_code == 400, r.text


def test_register_rejects_double_at(client, sqlite_factory):
    _seed_org(sqlite_factory)
    r = client.post(
        "/auth/register",
        json={"email": "a@b@example.com", "password": "hunter2secret"},
    )
    assert r.status_code == 400, r.text
