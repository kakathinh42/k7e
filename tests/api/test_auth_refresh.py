"""POST /auth/refresh — re-mint an active session before its JWT expires.

Only a first-party SESSION token (iss == session_issuer) may refresh: an
expired token, a foreign-issuer token, and a missing header all 401.
"""

from __future__ import annotations

import time

import jwt as pyjwt
import pytest
from k7e_api.config import get_settings
from k7e_api.jwt_auth import verify_token
from k7e_api.models import User
from k7e_api.password_auth import hash_password
from k7e_api.session_auth import mint_session
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


def _seed_user(sqlite_factory, email: str) -> None:
    """Seed a native User row so refresh's account re-check finds an account."""
    with sqlite_factory() as s:
        if s.execute(select(User).where(User.email == email)).scalar_one_or_none() is None:
            s.add(
                User(
                    email=email,
                    password_hash=hash_password("hunter2secret"),
                    org_id=_ORG,
                )
            )
            s.commit()


def test_refresh_valid_session_returns_fresh_session(client, sqlite_factory):
    _seed_user(sqlite_factory, "alice@example.com")
    settings = get_settings()
    original = mint_session("alice@example.com", settings)
    original_exp = verify_token(original, settings)["exp"]

    r = client.post("/auth/refresh", headers={"Authorization": f"Bearer {original}"})
    assert r.status_code == 200, r.text

    fresh = r.json()["session_token"]
    claims = verify_token(fresh, settings)
    assert claims["sub"] == "alice@example.com"
    assert claims["iss"] == settings.session_issuer
    # Fresh lifetime: the re-minted token's exp is no earlier than the original's.
    assert claims["exp"] >= original_exp


def test_refresh_missing_authorization_header_401(client):
    r = client.post("/auth/refresh")
    assert r.status_code == 401, r.text


def test_refresh_expired_session_401(client):
    settings = get_settings()
    now = int(time.time())
    expired = pyjwt.encode(
        {
            "sub": "alice@example.com",
            "email": "alice@example.com",
            "iss": settings.session_issuer,
            "iat": now - 7200,
            "exp": now - 3600,
        },
        settings.session_signing_secret,
        algorithm="HS256",
    )
    r = client.post("/auth/refresh", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401, r.text


def test_refresh_foreign_issuer_401(client):
    settings = get_settings()
    now = int(time.time())
    foreign = pyjwt.encode(
        {
            "sub": "attacker@example.com",
            "iss": "some-other-idp",
            "iat": now,
            "exp": now + 3600,
        },
        settings.session_signing_secret,
        algorithm="HS256",
    )
    r = client.post("/auth/refresh", headers={"Authorization": f"Bearer {foreign}"})
    assert r.status_code == 401, r.text


def test_refresh_garbage_token_401(client):
    r = client.post("/auth/refresh", headers={"Authorization": "Bearer not-a-real-jwt"})
    assert r.status_code == 401, r.text


def test_refresh_no_account_401(client):
    """A validly-signed, unexpired session token whose email has NO User row →
    401. A disabled/deleted account must not keep refreshing a fresh session."""
    settings = get_settings()
    # No _seed_user: the account does not exist in the DB.
    tok = mint_session("ghost@example.com", settings)
    r = client.post("/auth/refresh", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401, r.text
