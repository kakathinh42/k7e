"""M7: get_principal resolves a verified Bearer JWT; header seam preserved."""

from __future__ import annotations

import time

import jwt
import k7e_api.auth as auth
import pytest
from fastapi import HTTPException
from k7e_api.auth import get_principal
from k7e_api.config import Settings


def _settings(**over):
    # env="dev": the HS256 shared-secret path is dev-env-only since the web-SSO
    # dev-secret guard; prod-specific behavior is exercised with explicit
    # env="prod" overrides below (where no HS256 verification occurs).
    base = dict(
        env="dev",
        jwt_enabled=True,
        jwt_dev_secret="s3cret",
        jwt_issuer="dp",
        jwt_audience="wiki",
    )
    base.update(over)
    return Settings(**base)


def _token(**claims):
    payload = {
        "sub": "alice",
        "iss": "dp",
        "aud": "wiki",
        "exp": int(time.time()) + 600,
    }
    payload.update(claims)
    return jwt.encode(payload, "s3cret", algorithm="HS256")


def test_valid_jwt_becomes_principal(monkeypatch):
    monkeypatch.setattr(auth, "get_settings", _settings)
    p = get_principal(authorization=f"Bearer {_token()}")
    assert p.user_id == "alice"
    assert p.kind == "user"
    assert p.roles == [] and p.groups == []


def test_invalid_jwt_401(monkeypatch):
    monkeypatch.setattr(auth, "get_settings", _settings)
    with pytest.raises(HTTPException) as exc:
        get_principal(authorization="Bearer not.a.jwt")
    assert exc.value.status_code == 401


def test_prod_jwt_enabled_ignores_user_headers(monkeypatch):
    # No Bearer token is sent, so no HS256 verification happens — only the
    # fail-closed prod branch is exercised; env="prod" stays meaningful here.
    monkeypatch.setattr(auth, "get_settings", lambda: _settings(env="prod"))
    p = get_principal(x_user_id="admin-user", x_user_roles="admin")
    assert p.user_id == "anonymous"
    assert p.roles == []


def test_dev_no_token_keeps_header_seam(monkeypatch):
    monkeypatch.setattr(auth, "get_settings", lambda: _settings(env="dev"))
    p = get_principal(x_user_id="bob", x_user_roles="editor")
    assert p.user_id == "bob"
    assert "editor" in p.roles


def test_jwt_disabled_uses_headers(monkeypatch):
    monkeypatch.setattr(auth, "get_settings", lambda: Settings(env="prod", jwt_enabled=False))
    p = get_principal(x_user_id="carol", x_user_roles="editor")
    assert p.user_id == "carol" and "editor" in p.roles


def test_jwks_unavailable_is_503_not_401(monkeypatch):
    # A JWKS/IdP outage is a retryable 503, distinct from a bad-token 401.
    import k7e_api.jwt_auth as jwt_auth

    jwt_auth._JWKS_CACHE.clear()

    def _boom(url):
        raise RuntimeError("network down")

    monkeypatch.setattr(jwt_auth, "_fetch_jwks", _boom)
    monkeypatch.setattr(
        auth,
        "get_settings",
        lambda: Settings(
            env="prod",
            jwt_enabled=True,
            jwt_jwks_url="https://idp/jwks",
            jwt_issuer="dp",
        ),
    )
    # RS256 mode (no dev_secret) → verification needs the JWKS → cold-cache fetch fails.
    tok = jwt.encode(
        {"sub": "x", "iss": "dp", "exp": int(time.time()) + 60},
        "k",
        algorithm="HS256",
        headers={"kid": "k1"},
    )
    with pytest.raises(HTTPException) as exc:
        get_principal(authorization=f"Bearer {tok}")
    assert exc.value.status_code == 503
