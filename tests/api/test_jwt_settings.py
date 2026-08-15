"""M7: JWT settings (off by default) + pyjwt import available."""

from __future__ import annotations

import json

import pytest
from k7e_api.config import Settings
from pydantic import ValidationError


def test_jwt_defaults_off(monkeypatch):
    for var in (
        "JWT_ENABLED",
        "JWT_JWKS_URL",
        "JWT_ISSUER",
        "JWT_AUDIENCE",
        "JWT_DEV_SECRET",
        "JWT_TRUSTED_ISSUERS",
        "JWT_IDENTITY_CLAIM",
    ):
        monkeypatch.delenv(var, raising=False)
    s = Settings()
    assert s.jwt_enabled is False
    assert s.jwt_jwks_url == ""
    assert s.jwt_issuer == ""
    assert s.jwt_audience == ""
    assert s.jwt_dev_secret == ""
    assert s.jwt_leeway_seconds == 60
    assert s.jwt_trusted_issuers == ""
    assert s.jwt_identity_claim == "sub"


def test_trusted_issuers_valid_json_accepted():
    entries = json.dumps(
        [
            {"issuer": "https://a.example", "jwks_url": "https://a.example/jwks"},
            {
                "issuer": "https://b.example",
                "jwks_url": "https://b.example/jwks",
                "audience": "k7e",
                "identity_claim": "email",
            },
        ]
    )
    s = Settings(jwt_trusted_issuers=entries)
    assert json.loads(s.jwt_trusted_issuers)[1]["identity_claim"] == "email"


def test_trusted_issuers_blank_ok():
    assert Settings(jwt_trusted_issuers="  ").jwt_trusted_issuers == "  "


@pytest.mark.parametrize(
    "raw",
    [
        "{not json",
        '{"issuer": "a"}',  # object, not array
        '[{"issuer": "https://a.example"}]',  # missing jwks_url
        '[{"jwks_url": "https://a.example/jwks"}]',  # missing issuer
        '[{"issuer": "", "jwks_url": "https://a.example/jwks"}]',  # empty issuer
        '["https://a.example"]',  # entry not an object
    ],
)
def test_trusted_issuers_malformed_rejected(raw):
    with pytest.raises(ValidationError):
        Settings(jwt_trusted_issuers=raw)


def test_pyjwt_crypto_available():
    import jwt
    from jwt.algorithms import RSAAlgorithm  # requires pyjwt[crypto]/cryptography

    assert hasattr(jwt, "decode") and RSAAlgorithm is not None
