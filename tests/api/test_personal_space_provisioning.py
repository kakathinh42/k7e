"""JIT personal-space provisioning (personal-spaces spec Piece 2).

provision_personal_space creates a bare Space with owner_user_id set plus two
direct user grants (editor + admin) — no Team, no Membership, no group. It is
idempotent (second call returns the same row, no new grants), disambiguates
slug collisions with a hash suffix, and resolves the concurrent-first-ingest
race by re-reading the winner's row after an IntegrityError.
"""

from __future__ import annotations

import hashlib
import uuid

import pytest
from k7e_api.models import Organization, RoleGrant, Space
from k7e_api.personal_spaces import personal_space_for, provision_personal_space
from sqlalchemy import select
from sqlalchemy.orm import Session

_ORG_ID = uuid.UUID("00000000-0000-0000-0000-0000000000f1")


def _seed_org(s: Session) -> None:
    s.add(Organization(id=_ORG_ID, slug="personal-org", name="Personal Org"))
    s.flush()


def _grants_for_space(s: Session, space_id: uuid.UUID) -> list[RoleGrant]:
    return (
        s.execute(
            select(RoleGrant).where(
                RoleGrant.scope_kind == "space", RoleGrant.scope_id == space_id
            )
        )
        .scalars()
        .all()
    )


def test_provision_creates_space_with_owner_and_grants(sqlite_factory):
    with sqlite_factory() as s:
        _seed_org(s)
        space = provision_personal_space(s, user_id="alice", org_id=_ORG_ID)
        s.commit()

        assert space.owner_user_id == "alice"
        assert space.org_id == _ORG_ID
        assert space.slug == "user-alice"
        assert space.visibility == "members"

        grants = _grants_for_space(s, space.id)
        assert len(grants) == 2, f"expected exactly editor+admin, got {grants}"
        assert all(g.principal_kind == "user" for g in grants)
        assert all(g.principal_id == "alice" for g in grants)
        assert {g.role for g in grants} == {"editor", "admin"}


def test_provision_is_idempotent(sqlite_factory):
    with sqlite_factory() as s:
        _seed_org(s)
        first = provision_personal_space(s, user_id="alice", org_id=_ORG_ID)
        s.commit()
        first_id = first.id

    with sqlite_factory() as s:
        second = provision_personal_space(s, user_id="alice", org_id=_ORG_ID)
        s.commit()
        assert second.id == first_id
        # No new grants beyond the original editor+admin pair.
        assert len(_grants_for_space(s, first_id)) == 2


def test_slug_collision_gets_hash_suffix(sqlite_factory):
    """Pre-existing space with the colliding slug → provision suffixes and succeeds."""
    with sqlite_factory() as s:
        _seed_org(s)
        # 'al.ice' slugifies to 'user-al-ice'; occupy that slug first.
        s.add(Space(org_id=_ORG_ID, slug="user-al-ice", name="Squatter"))
        s.flush()

        space = provision_personal_space(s, user_id="al.ice", org_id=_ORG_ID)
        s.commit()

        expected_suffix = hashlib.sha256(b"al.ice").hexdigest()[:6]
        assert space.slug == f"user-al-ice-{expected_suffix}"
        assert space.owner_user_id == "al.ice"
        assert {g.role for g in _grants_for_space(s, space.id)} == {"editor", "admin"}


def test_concurrent_provision_loser_returns_winner_row(sqlite_factory, monkeypatch):
    """Race: loser's flush hits the (org_id, owner_user_id) unique index and
    re-reads the winner's row instead of raising."""
    import k7e_api.personal_spaces as ps

    with sqlite_factory() as s:
        _seed_org(s)
        s.commit()

    # The winner provisions first (committed, so the unique index will fire
    # for the loser at flush).
    with sqlite_factory() as s:
        winner = provision_personal_space(s, user_id="alice", org_id=_ORG_ID)
        s.commit()
        winner_id = winner.id

    # Simulate the loser's stale existence check: the first personal_space_for
    # call reports "no personal space yet"; later calls (the post-IntegrityError
    # re-read) delegate to the real lookup.
    real_lookup = ps.personal_space_for
    calls = {"n": 0}

    def _stale_then_real(session, *, user_id, org_id):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return real_lookup(session, user_id=user_id, org_id=org_id)

    monkeypatch.setattr(ps, "personal_space_for", _stale_then_real)

    with sqlite_factory() as s:
        loser_result = ps.provision_personal_space(s, user_id="alice", org_id=_ORG_ID)
        assert loser_result.id == winner_id
        assert calls["n"] >= 2, "loser must have re-read after the IntegrityError"
        # The winner's grants are untouched and no duplicates were added.
        assert len(_grants_for_space(s, winner_id)) == 2


def test_slugify_edge_cases():
    from k7e_api.personal_spaces import _slugify_sub

    assert _slugify_sub("Alice.Smith@corp") == "user-alice-smith-corp"
    assert _slugify_sub("...") == "user-user"  # all-symbol sub → fallback base
    assert len(_slugify_sub("x" * 500)) <= 120


def test_personal_space_for_scopes_by_org(sqlite_factory):
    """The lookup is org-scoped: the same user in another org has no space."""
    other_org = uuid.UUID("00000000-0000-0000-0000-0000000000f2")
    with sqlite_factory() as s:
        _seed_org(s)
        s.add(Organization(id=other_org, slug="other-org", name="Other"))
        s.flush()
        provision_personal_space(s, user_id="alice", org_id=_ORG_ID)
        s.commit()

        assert personal_space_for(s, user_id="alice", org_id=_ORG_ID) is not None
        assert personal_space_for(s, user_id="alice", org_id=other_org) is None


def test_provision_reraises_when_no_winner_found(sqlite_factory):
    """IntegrityError with no winner row (a genuine slug conflict — both the
    base AND the suffixed slug are occupied by non-personal spaces, so the
    post-error re-read finds no personal space) propagates rather than being
    swallowed."""
    from sqlalchemy.exc import IntegrityError

    suffixed = f"user-bob-{hashlib.sha256(b'bob').hexdigest()[:6]}"
    with sqlite_factory() as s:
        _seed_org(s)
        s.add(Space(org_id=_ORG_ID, slug="user-bob", name="Squatter"))
        s.add(Space(org_id=_ORG_ID, slug=suffixed, name="Squatter 2"))
        s.commit()

    with sqlite_factory() as s:
        with pytest.raises(IntegrityError):
            provision_personal_space(s, user_id="bob", org_id=_ORG_ID)
