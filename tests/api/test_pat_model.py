"""PersonalAccessToken model (PAT SSO Phase 1, Task 3)."""

from __future__ import annotations

from k7e_api.models import PersonalAccessToken
from sqlalchemy import select


def test_pat_persists_with_nullable_lifecycle_cols(sqlite_factory):
    with sqlite_factory() as s:
        s.add(
            PersonalAccessToken(
                user_id="alice@example.com",
                name="laptop",
                token_hash="a" * 64,
            )
        )
        s.commit()
        p = s.execute(select(PersonalAccessToken)).scalar_one()
        assert p.id is not None
        assert p.user_id == "alice@example.com"
        assert p.token_hash == "a" * 64
        assert p.created_at is not None
        # lifecycle columns default to unset
        assert p.last_used_at is None
        assert p.expires_at is None
        assert p.revoked_at is None
