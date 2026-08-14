"""M7: verify_token — HS256 dev mode + RS256 JWKS mode, no network."""

from __future__ import annotations

import json
import time

import jwt
import k7e_api.jwt_auth as jwt_auth
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from k7e_api.config import Settings
from k7e_api.jwt_auth import JwtError, verify_token


def _hs_settings(**over):
    base = dict(
        jwt_enabled=True,
        jwt_dev_secret="s3cret",
        jwt_issuer="devportal",
        jwt_audience="k7e",
    )
    base.update(over)
    return Settings(**base)


def _hs_token(secret="s3cret", **claims):
    payload = {
        "sub": "u1",
        "iss": "devportal",
        "aud": "k7e",
        "exp": int(time.time()) + 3600,
    }
    payload.update(claims)
    return jwt.encode(payload, secret, algorithm="HS256")


def test_hs256_valid_returns_claims():
    claims = verify_token(_hs_token(), _hs_settings())
    assert claims["sub"] == "u1"


def test_hs256_expired_raises():
    with pytest.raises(JwtError):
        verify_token(_hs_token(exp=int(time.time()) - 10), _hs_settings())


def test_hs256_bad_signature_raises():
    with pytest.raises(JwtError):
        verify_token(_hs_token(secret="wrong"), _hs_settings())


def test_hs256_wrong_issuer_raises():
    with pytest.raises(JwtError):
        verify_token(_hs_token(iss="evil"), _hs_settings())


def test_hs256_wrong_audience_raises():
    with pytest.raises(JwtError):
        verify_token(_hs_token(aud="other"), _hs_settings())


def test_hs256_missing_sub_raises():
    tok = jwt.encode(
        {"iss": "devportal", "aud": "k7e", "exp": int(time.time()) + 60},
        "s3cret",
        algorithm="HS256",
    )
    with pytest.raises(JwtError):
        verify_token(tok, _hs_settings())


def test_hs256_non_numeric_exp_is_401_not_500():
    # A signed token with a malformed exp must be a clean JwtError (401), not a crash.
    tok = jwt.encode(
        {"sub": "u1", "iss": "devportal", "aud": "k7e", "exp": "soon"},
        "s3cret",
        algorithm="HS256",
    )
    with pytest.raises(JwtError):
        verify_token(tok, _hs_settings())


def test_rs256_via_jwks(monkeypatch):
    jwt_auth._JWKS_CACHE.clear()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub_jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    pub_jwk["kid"] = "test-kid"
    jwks = {"keys": [pub_jwk]}
    monkeypatch.setattr(jwt_auth, "_fetch_jwks", lambda url: jwks)

    s = Settings(
        jwt_enabled=True,
        jwt_jwks_url="https://idp/jwks",
        jwt_issuer="idp",
        jwt_audience="k7e",
    )
    token = jwt.encode(
        {"sub": "u9", "iss": "idp", "aud": "k7e", "exp": int(time.time()) + 3600},
        key,
        algorithm="RS256",
        headers={"kid": "test-kid"},
    )
    assert verify_token(token, s)["sub"] == "u9"


def test_rs256_cold_cache_fetch_failure_raises(monkeypatch):
    jwt_auth._JWKS_CACHE.clear()

    def _boom(url):
        raise RuntimeError("network down")

    monkeypatch.setattr(jwt_auth, "_fetch_jwks", _boom)
    s = Settings(jwt_enabled=True, jwt_jwks_url="https://idp/jwks", jwt_issuer="idp")
    token = jwt.encode(
        {"sub": "x", "iss": "idp", "exp": int(time.time()) + 60},
        "k",
        algorithm="HS256",
        headers={"kid": "k1"},
    )
    with pytest.raises(JwtError):
        verify_token(token, s)
