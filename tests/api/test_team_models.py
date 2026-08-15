"""Team / Membership ORM models + Space.visibility (Task 1 — M3 Step A).

A Team owns one Space (unique space_id) and is identified by (org_id, slug).
Membership binds a user to a team with a role (owner|admin|member|viewer) and
is unique on (team_id, user_id). Space.visibility defaults to 'members'
(advisory; grants govern access).
"""

from __future__ import annotations

import uuid

import pytest
from k7e_api.models import Membership, Organization, Space, Team
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

_ORG_ID = uuid.UUID("00000000-0000-0000-0000-0000000000e1")
_SPACE_ID = uuid.UUID("00000000-0000-0000-0000-0000000000e2")


def _seed_org_space(s: Session) -> Space:
    org = Organization(id=_ORG_ID, slug="team-org", name="Team Org")
    space = Space(id=_SPACE_ID, org_id=_ORG_ID, slug="eng", name="Engineering")
    s.add_all([org, space])
    s.flush()
    return space


def test_team_round_trip_and_space_visibility_default(sqlite_factory):
    """A Team persists bound to a Space; Space.visibility defaults to 'members'."""
    with sqlite_factory() as s:
        space = _seed_org_space(s)
        team = Team(
            org_id=_ORG_ID,
            space_id=space.id,
            slug="eng",
            name="Engineering Team",
            created_by="alice",
        )
        s.add(team)
        s.flush()
        assert team.id is not None
        assert team.created_at is not None
        # Space.visibility defaults to 'members' (Python-side default).
        assert space.visibility == "members"

        reloaded = s.get(Team, team.id)
        assert reloaded.slug == "eng"
        assert reloaded.org_id == _ORG_ID
        assert reloaded.space_id == space.id


def test_membership_two_roles_and_unique_constraint(sqlite_factory):
    """Owner + member Memberships persist; duplicate (team_id, user_id) raises."""
    with sqlite_factory() as s:
        space = _seed_org_space(s)
        team = Team(
            org_id=_ORG_ID,
            space_id=space.id,
            slug="eng",
            name="Engineering",
            created_by="alice",
        )
        s.add(team)
        s.flush()
        owner = Membership(team_id=team.id, user_id="alice", role="owner")
        member = Membership(team_id=team.id, user_id="bob", role="member")
        s.add_all([owner, member])
        s.flush()
        assert owner.role == "owner"
        assert member.role == "member"

        dup = Membership(team_id=team.id, user_id="alice", role="member")
        s.add(dup)
        with pytest.raises(IntegrityError):
            s.flush()
        s.rollback()


def test_team_org_slug_unique_constraint(sqlite_factory):
    """Two teams in the same org with the same slug is rejected."""
    with sqlite_factory() as s:
        space = _seed_org_space(s)
        s.add(
            Team(
                org_id=_ORG_ID,
                space_id=space.id,
                slug="eng",
                name="Engineering",
                created_by="alice",
            )
        )
        s.flush()
        space2 = Space(org_id=_ORG_ID, slug="eng2", name="Engineering 2")
        s.add(space2)
        s.flush()
        dup = Team(
            org_id=_ORG_ID,
            space_id=space2.id,
            slug="eng",
            name="Engineering Dup",
            created_by="carol",
        )
        s.add(dup)
        with pytest.raises(IntegrityError):
            s.flush()
        s.rollback()
