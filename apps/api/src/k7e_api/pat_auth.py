"""Personal Access Token generation + hashing (PAT SSO).

A PAT is a high-entropy ``wpat_``-prefixed token; only its sha256 hash is stored
(``PersonalAccessToken.token_hash``). Mirrors ``app_auth`` for ClientApp keys.
"""

from __future__ import annotations

import hashlib
import secrets

_PAT_PREFIX = "wpat_"


def generate_pat() -> tuple[str, str]:
    """Return ``(plaintext_token, sha256_hex)``. Store only the hash."""
    plaintext = _PAT_PREFIX + secrets.token_urlsafe(32)
    return plaintext, hash_pat(plaintext)


def hash_pat(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def is_pat(token: str) -> bool:
    """True if ``token`` is a PAT (so the Bearer path routes it to PAT lookup)."""
    return token.startswith(_PAT_PREFIX)
