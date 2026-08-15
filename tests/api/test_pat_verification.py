"""wpat_ PAT verification in get_principal (PAT SSO Phase 1, Task 5 — the crux).

A PAT presented as Authorization: Bearer wpat_... must resolve to the OWNING
user (verified), stamp last_used_at, and be dead when revoked/expired/unknown —
while a non-PAT bearer (a real session JWT) still verifies unchanged.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from k7e_api.config import get_settings
from k7e_api.models import PersonalAccessToken
from k7e_api.pat_auth import hash_pat
from k7e_api.session_auth import mint_session
from sqlalchemy import select


@pytest.fixture()
def client(api_client, monkeypatch):
    monkeypatch.setenv("JWT_ENABLED", "true")
    monkeypatch.setenv("SESSION_SIGNING_SECRET", "test-secret")
    monkeypatch.setenv("SESSION_ISSUER", "k7e-session")
    monkeypatch.setenv("ENV", "prod")
    get_settings.cache_clear()
    yield api_client
    get_settings.cache_clear()


def _seed_pat(sqlite_factory, *, user_id, token, expires_at=None, revoked_at=None):
    with sqlite_factory() as s:
        s.add(
            PersonalAccessToken(
                user_id=user_id,
                name="t",
                token_hash=hash_pat(token),
                expires_at=expires_at,
                revoked_at=revoked_at,
            )
        )
        s.commit()


def _pat_hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_valid_pat_resolves_to_owner_and_stamps_last_used(client, sqlite_factory):
    _seed_pat(sqlite_factory, user_id="alice@example.com", token="wpat_alicevalid")
    # authenticate the /pat listing WITH the PAT itself → resolves to alice
    r = client.get("/pat", headers=_pat_hdr("wpat_alicevalid"))
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1  # alice's one token, proving the owner resolved
    with sqlite_factory() as s:
        row = s.execute(select(PersonalAccessToken)).scalar_one()
        assert row.last_used_at is not None


def test_pat_scoped_to_owner_only(client, sqlite_factory):
    _seed_pat(sqlite_factory, user_id="alice@example.com", token="wpat_alicetok")
    _seed_pat(sqlite_factory, user_id="bob@example.com", token="wpat_bobtok")
    r = client.get("/pat", headers=_pat_hdr("wpat_alicetok"))
    assert r.status_code == 200
    assert len(r.json()) == 1  # ONLY alice's token, not bob's


def test_revoked_pat_401(client, sqlite_factory):
    _seed_pat(
        sqlite_factory,
        user_id="alice@example.com",
        token="wpat_revoked",
        revoked_at=datetime.now(timezone.utc),
    )
    assert client.get("/pat", headers=_pat_hdr("wpat_revoked")).status_code == 401


def test_expired_pat_401(client, sqlite_factory):
    _seed_pat(
        sqlite_factory,
        user_id="alice@example.com",
        token="wpat_expired",
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    assert client.get("/pat", headers=_pat_hdr("wpat_expired")).status_code == 401


def test_unknown_pat_401(client):
    assert client.get("/pat", headers=_pat_hdr("wpat_nonexistent")).status_code == 401


def test_non_pat_bearer_still_verifies_as_session(client, sqlite_factory):
    # a real session JWT (not a wpat_) authenticates unchanged — no regression.
    tok = mint_session("bob@example.com", get_settings())
    r = client.get("/pat", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200  # bob, empty list
