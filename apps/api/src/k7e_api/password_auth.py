"""Password hashing for native email+password accounts (bcrypt).

Only the salted bcrypt hash is ever stored (``User.password_hash``); the
plaintext is verified with a constant-time compare and never persisted.
"""

from __future__ import annotations

import bcrypt

# bcrypt (>=4.1) RAISES on inputs longer than 72 bytes (it does NOT silently
# truncate) — callers must reject overlong passwords before hashing.
BCRYPT_MAX_BYTES = 72

# A pre-computed valid bcrypt hash used ONLY to equalize login timing when the
# account does not exist: verify the submitted password against this in the
# no-such-user branch so both branches run exactly one bcrypt compare, closing
# the user-enumeration timing side-channel. Not a secret.
DUMMY_HASH = "$2b$12$EpaoAnDlo/hV2R28ajWOS.oJUZywzPZ15p9avas9LHP27pz5DR1rC"


def hash_password(plaintext: str) -> str:
    """Return a salted bcrypt hash of ``plaintext`` (per-hash random salt)."""
    return bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plaintext: str, hashed: str) -> bool:
    """Constant-time check of ``plaintext`` against a stored bcrypt ``hashed``.

    Returns False (never raises) on a malformed/empty stored hash so callers
    can treat every failure as a generic auth failure.
    """
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False
