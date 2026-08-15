"""Self-issued session tokens for native (email + password) login.

k7e is the SOLE minter and verifier of these tokens, so a symmetric
(HS256) signature with ``session_signing_secret`` is safe (the sprawl risk
requires multiple independent verifiers).
"""

from __future__ import annotations

import time

import jwt


def mint_session(email: str, settings) -> str:
    now = int(time.time())
    payload = {
        "sub": email,
        "email": email,
        "iss": settings.session_issuer,
        "iat": now,
        "exp": now + int(settings.session_ttl_seconds),
    }
    return jwt.encode(payload, settings.session_signing_secret, algorithm="HS256")
