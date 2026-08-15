"""Web SSO: trusted-issuer list — routing by iss, per-issuer JWKS/aud/identity."""

from __future__ import annotations

import json
import time

import jwt
import k7e_api.jwt_auth as jwt_auth
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from k7e_api.config import Settings
from k7e_api.jwt_auth import JwtError, identity_from_claims, verify_token

# RSA keygen is slow; generate once per module.
_KEY_A = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_KEY_B = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk(key, kid):
    entry = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    entry["kid"] = kid
    return entry


_JWKS_DOCS = {
    "https://a.example/jwks": {"keys": [_jwk(_KEY_A, "kid-a")]},
    "https://b.example/jwks": {"keys": [_jwk(_KEY_B, "kid-b")]},
}

_TRUSTED = json.dumps(
    [
        {
            "issuer": "https://a.example",
            "jwks_url": "https://a.example/jwks",
            "audience": "k7e",
        },
        {
            "issuer": "https://b.example",
            "jwks_url": "https://b.example/jwks",
            "identity_claim": "email",
        },
    ]
)


@pytest.fixture()
def jwks(monkeypatch):
    jwt_auth._JWKS_CACHE.clear()
    monkeypatch.setattr(jwt_auth, "_fetch_jwks", lambda url: _JWKS_DOCS[url])


def _settings(**over):
    base = dict(env="prod", jwt_enabled=True, jwt_trusted_issuers=_TRUSTED)
    base.update(over)
    return Settings(**base)


def _token(key=_KEY_A, kid="kid-a", **claims):
    payload = {
        "sub": "alice",
        "iss": "https://a.example",
        "aud": "k7e",
        "exp": int(time.time()) + 3600,
    }
    payload.update(claims)
    # ``None`` means "omit the claim" (PyJWT refuses to encode iss/aud=None).
    payload = {k: v for k, v in payload.items() if v is not None}
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": kid})


def test_issuer_a_verifies_via_a_jwks(jwks):
    assert verify_token(_token(), _settings())["sub"] == "alice"


def test_issuer_b_verifies_via_b_jwks(jwks):
    tok = _token(key=_KEY_B, kid="kid-b", iss="https://b.example", aud=None)
    assert verify_token(tok, _settings())["iss"] == "https://b.example"


def test_cross_signed_token_rejected(jwks):
    # Claims iss=a but signed with b's key under a's kid → signature failure.
    tok = _token(key=_KEY_B, kid="kid-a")
    with pytest.raises(JwtError):
        verify_token(tok, _settings())


def test_unknown_kid_rejected(jwks):
    # Claims iss=a, signed by b with b's kid → a's JWKS has no such kid.
    tok = _token(key=_KEY_B, kid="kid-b")
    with pytest.raises(JwtError):
        verify_token(tok, _settings())


def test_unknown_issuer_rejected_before_jwks_fetch(monkeypatch):
    jwt_auth._JWKS_CACHE.clear()

    def _boom(url):  # pragma: no cover - must not be reached
        raise AssertionError("JWKS fetched for untrusted issuer")

    monkeypatch.setattr(jwt_auth, "_fetch_jwks", _boom)
    with pytest.raises(JwtError, match="untrusted or missing issuer"):
        verify_token(_token(iss="https://evil.example"), _settings())


def test_missing_issuer_rejected(jwks):
    with pytest.raises(JwtError, match="untrusted or missing issuer"):
        verify_token(_token(iss=None), _settings())


def test_per_issuer_audience_enforced(jwks):
    with pytest.raises(JwtError):
        verify_token(_token(aud="other"), _settings())
    # Issuer b has no audience configured → aud not required.
    tok = _token(key=_KEY_B, kid="kid-b", iss="https://b.example", aud=None)
    assert verify_token(tok, _settings())


def test_legacy_single_issuer_still_verifies(jwks):
    s = _settings(
        jwt_trusted_issuers="",
        jwt_jwks_url="https://a.example/jwks",
        jwt_issuer="https://a.example",
        jwt_audience="k7e",
    )
    assert verify_token(_token(), s)["sub"] == "alice"


def test_legacy_wildcard_no_issuer_check(jwks):
    # Pre-list semantics: jwks_url set, jwt_issuer empty → any iss (or none)
    # verifies against that JWKS.
    s = _settings(jwt_trusted_issuers="", jwt_jwks_url="https://a.example/jwks")
    assert verify_token(_token(iss="whatever", aud=None), s)["sub"] == "alice"
    assert verify_token(_token(iss=None, aud=None), s)["sub"] == "alice"


def test_legacy_and_list_compose(jwks):
    s = _settings(
        jwt_trusted_issuers=json.dumps(
            [{"issuer": "https://b.example", "jwks_url": "https://b.example/jwks"}]
        ),
        jwt_jwks_url="https://a.example/jwks",
        jwt_issuer="https://a.example",
        jwt_audience="k7e",
    )
    assert verify_token(_token(), s)["sub"] == "alice"
    tok_b = _token(key=_KEY_B, kid="kid-b", iss="https://b.example", aud=None)
    assert verify_token(tok_b, s)["sub"] == "alice"


def test_dev_secret_ignored_outside_dev_env(jwks):
    # HS256 token signed with the shared secret must NOT verify in prod.
    s = _settings(jwt_dev_secret="s3cret")
    hs = jwt.encode(
        {
            "sub": "u",
            "iss": "https://a.example",
            "aud": "k7e",
            "exp": int(time.time()) + 60,
        },
        "s3cret",
        algorithm="HS256",
    )
    with pytest.raises(JwtError):
        verify_token(hs, s)


def test_dev_secret_honored_in_dev_env():
    s = Settings(env="dev", jwt_enabled=True, jwt_dev_secret="s3cret")
    hs = jwt.encode({"sub": "u", "exp": int(time.time()) + 60}, "s3cret", algorithm="HS256")
    assert verify_token(hs, s)["sub"] == "u"


def test_identity_claim_per_issuer(jwks):
    claims = verify_token(
        _token(
            key=_KEY_B,
            kid="kid-b",
            iss="https://b.example",
            aud=None,
            email="alice@example.com",
        ),
        _settings(),
    )
    assert identity_from_claims(claims, _settings()) == "alice@example.com"


def test_identity_claim_missing_is_error_not_sub_fallback(jwks):
    claims = verify_token(
        _token(key=_KEY_B, kid="kid-b", iss="https://b.example", aud=None),
        _settings(),
    )
    with pytest.raises(JwtError, match="identity claim"):
        identity_from_claims(claims, _settings())


def test_identity_claim_global_default_and_override(jwks):
    claims = verify_token(_token(email="a@x.com"), _settings())
    # Issuer a has no per-issuer claim → global default "sub".
    assert identity_from_claims(claims, _settings()) == "alice"
    # Global override applies to issuers without their own identity_claim.
    assert identity_from_claims(claims, _settings(jwt_identity_claim="email")) == "a@x.com"


def test_identity_from_claims_normalizes_email_but_not_opaque_sub():
    """Email-shaped identity claims are case-folded so one human maps to one
    user_id across seams; an opaque non-email ``sub`` is left byte-for-byte."""
    from types import SimpleNamespace

    settings = SimpleNamespace()  # no issuer config → global default claim "sub"
    assert identity_from_claims({"sub": "Alice@Example.com"}, settings) == "alice@example.com"
    assert identity_from_claims({"sub": "AbC123"}, settings) == "AbC123"
