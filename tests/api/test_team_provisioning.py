"""provision_team + team_groups_for_user + can_admin (Task 2 — M3 Step A).

provision_team atomically creates a members-only Space, the team-group editor
grant, the owner's user admin grant, and the owner Membership. team_groups_for_user
resolves team:{slug} groups per-request (removal cuts access). can_admin admits
the owner via the user admin grant.
"""

from __future__ import annotations

import uuid

import pytest
from k7e_api.auth import Principal
from k7e_api.models import Membership, Organization, RoleGrant, Space
from k7e_api.rbac import HierarchicalRbacAuthorizationService, Scope
from k7e_api.teams import ReservedSlugError, provision_team, team_groups_for_user
from sqlalchemy import select
from sqlalchemy.orm import Session

_ORG_ID = uuid.UUID("00000000-0000-0000-0000-0000000000e1")


def _seed_org(s: Session) -> None:
    s.add(Organization(id=_ORG_ID, slug="team-org", name="Team Org"))
    s.flush()


def test_provision_team_creates_space_grants_and_owner(sqlite_factory):
    with sqlite_factory() as s:
        _seed_org(s)
        team = provision_team(s, slug="eng", name="Engineering", owner_id="alice", org_id=_ORG_ID)
        s.commit()

        space = s.get(Space, team.space_id)
        assert space.visibility == "members"
        assert space.org_id == _ORG_ID
        assert space.slug == "eng"

        # Team-group editor grant at the space (admits all members).
        group_grant = s.execute(
            select(RoleGrant).where(
                RoleGrant.principal_kind == "group",
                RoleGrant.principal_id == "team:eng",
                RoleGrant.role == "editor",
                RoleGrant.scope_kind == "space",
                RoleGrant.scope_id == space.id,
            )
        ).scalar_one()
        assert group_grant is not None

        # Owner's user admin grant at the space (drives can_admin).
        admin_grant = s.execute(
            select(RoleGrant).where(
                RoleGrant.principal_kind == "user",
                RoleGrant.principal_id == "alice",
                RoleGrant.role == "admin",
                RoleGrant.scope_kind == "space",
                RoleGrant.scope_id == space.id,
            )
        ).scalar_one()
        assert admin_grant is not None

        owner_membership = s.execute(
            select(Membership).where(Membership.team_id == team.id, Membership.user_id == "alice")
        ).scalar_one()
        assert owner_membership.role == "owner"


def test_team_groups_for_user_resolves_membership(sqlite_factory):
    with sqlite_factory() as s:
        _seed_org(s)
        provision_team(s, slug="eng", name="Engineering", owner_id="alice", org_id=_ORG_ID)
        s.commit()

    with sqlite_factory() as s:
        assert team_groups_for_user(s, "alice") == {"team:eng"}
        assert team_groups_for_user(s, "nobody") == set()


def test_team_groups_for_user_per_request_resolution(sqlite_factory):
    """Removing a Membership cuts the group on the next resolution (no cache)."""
    with sqlite_factory() as s:
        _seed_org(s)
        provision_team(s, slug="eng", name="Engineering", owner_id="alice", org_id=_ORG_ID)
        s.commit()

    with sqlite_factory() as s:
        assert team_groups_for_user(s, "alice") == {"team:eng"}
        m = s.execute(select(Membership).where(Membership.user_id == "alice")).scalar_one()
        s.delete(m)
        s.commit()
        assert team_groups_for_user(s, "alice") == set()


def test_can_admin_owner_via_grant_non_owner_denied(sqlite_factory):
    with sqlite_factory() as s:
        _seed_org(s)
        team = provision_team(s, slug="eng", name="Engineering", owner_id="alice", org_id=_ORG_ID)
        s.commit()
        space_id = team.space_id

    service = HierarchicalRbacAuthorizationService(session_factory=sqlite_factory)
    owner = Principal(user_id="alice", roles=[], groups=[])
    non_owner = Principal(user_id="bob", roles=[], groups=[])

    assert service.can_admin(owner, Scope("space", space_id)) is True
    assert service.can_admin(non_owner, Scope("space", space_id)) is False


def test_can_admin_header_back_compat(sqlite_factory):
    """X-User-Roles: admin short-circuits can_admin; viewer does not."""
    service = HierarchicalRbacAuthorizationService(session_factory=sqlite_factory)
    assert service.can_admin(Principal(user_id="alice", roles=["admin"], groups=[])) is True
    assert service.can_admin(Principal(user_id="alice", roles=["viewer"], groups=[])) is False


def test_provision_team_rejects_reserved_personal_slug(sqlite_factory):
    """'personal' is reserved for JIT-provisioned personal spaces, not teams."""
    with sqlite_factory() as s:
        _seed_org(s)
        with pytest.raises(ReservedSlugError):
            provision_team(s, slug="personal", name="Personal", owner_id="alice", org_id=_ORG_ID)
