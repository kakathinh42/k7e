"""Self-issued session: mint + verify on the dedicated self-issuer branch."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from k7e_api.jwt_auth import JwtError, verify_token
from k7e_api.session_auth import mint_session

_S = SimpleNamespace(
    session_signing_secret="s3cret",
    session_issuer="k7e-session",
    session_ttl_seconds=3600,
    jwt_leeway_seconds=60,
    jwt_dev_secret="",
    env="prod",
    jwt_trusted_issuers="",
    jwt_issuer="",
    jwt_jwks_url="",
    jwt_audience="",
)


def test_mint_then_verify_roundtrip():
    tok = mint_session("alice@example.com", _S)
    claims = verify_token(tok, _S)
    assert claims["sub"] == "alice@example.com"
    assert claims["iss"] == "k7e-session"


def test_foreign_token_claiming_self_iss_rejected():
    import jwt as pyjwt

    forged = pyjwt.encode(
        {"sub": "attacker@example.com", "iss": "k7e-session"},
        "WRONG-secret",
        algorithm="HS256",
    )
    with pytest.raises(JwtError):
        verify_token(forged, _S)


def test_identity_resolves_under_email_claim():
    from types import SimpleNamespace

    from k7e_api.jwt_auth import identity_from_claims, verify_token
    from k7e_api.session_auth import mint_session

    s = SimpleNamespace(
        session_signing_secret="s3cret",
        session_issuer="k7e-session",
        session_ttl_seconds=3600,
        jwt_leeway_seconds=60,
        jwt_dev_secret="",
        env="prod",
        jwt_trusted_issuers="",
        jwt_issuer="",
        jwt_jwks_url="",
        jwt_audience="",
        jwt_identity_claim="email",
    )
    claims = verify_token(mint_session("alice@example.com", s), s)
    assert identity_from_claims(claims, s) == "alice@example.com"


def test_missing_secret_fails_closed():
    import jwt as pyjwt

    no_secret_settings = SimpleNamespace(
        session_signing_secret="",
        session_issuer="k7e-session",
        session_ttl_seconds=3600,
        jwt_leeway_seconds=60,
        jwt_dev_secret="",
        env="prod",
        jwt_trusted_issuers="",
        jwt_issuer="",
        jwt_jwks_url="",
        jwt_audience="",
    )
    # Token claims the self-issuer but there's nothing to verify it with —
    # must fail closed, never fall through to JWKS/unsigned acceptance.
    tok = pyjwt.encode(
        {"sub": "alice@example.com", "iss": "k7e-session"},
        "anything",
        algorithm="HS256",
    )
    with pytest.raises(JwtError):
        verify_token(tok, no_secret_settings)
