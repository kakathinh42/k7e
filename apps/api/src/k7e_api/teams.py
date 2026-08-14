"""Team provisioning + membership→group resolution (M3 Step A).

``provision_team`` atomically creates a Team, a members-only Space, the
team-group editor grant, and the owner's admin grant + owner Membership — the
minimum composition that makes a team a self-sharing knowledge container.

``team_groups_for_user`` resolves the ``team:{slug}`` groups a principal gains
from their Memberships; ``get_principal_with_teams`` (in auth.py) unions these
into the request principal so the RBAC resolver's group-grant match admits
members automatically.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from k7e_api.models import Membership, RoleGrant, Space, Team


class ReservedSlugError(ValueError):
    """Raised when a team slug collides with a reserved namespace (e.g. 'personal')."""


def provision_team(
    session: Session,
    *,
    slug: str,
    name: str,
    owner_id: str,
    org_id: uuid.UUID,
) -> Team:
    """Atomically create a Team + its members-only Space + grants + owner.

    Creates, in the caller's session (uncommitted — the caller commits):
      1. ``Space(org_id, slug, name, visibility="members")``.
      2. ``Team(org_id, space_id, slug, name, created_by=owner_id)``.
      3. ``RoleGrant(group="team:{slug}", role="editor", scope=space)`` — every
         member (via the ``team:{slug}`` group) gets read+write.
      4. ``RoleGrant(user=owner_id, role="admin", scope=space)`` — the owner
         passes ``can_admin`` (membership management) at the team space.
      5. ``Membership(team, owner_id, role="owner")`` — owner-of-record.

    Returns the new Team (with ``.id`` and ``.space_id`` populated after the
    internal flushes).

    Raises ``ReservedSlugError`` for ``slug == "personal"`` — that namespace is
    reserved for JIT-provisioned personal spaces (``spaces.owner_user_id``),
    not team-owned ones.
    """
    if slug == "personal":
        raise ReservedSlugError("'personal' is a reserved slug")
    space = Space(org_id=org_id, slug=slug, name=name, visibility="members")
    session.add(space)
    session.flush()  # populate space.id
    team = Team(
        org_id=org_id,
        space_id=space.id,
        slug=slug,
        name=name,
        created_by=owner_id,
    )
    session.add(team)
    session.flush()  # populate team.id
    session.add(
        RoleGrant(
            principal_kind="group",
            principal_id=f"team:{slug}",
            role="editor",
            scope_kind="space",
            scope_id=space.id,
        )
    )
    session.add(
        RoleGrant(
            principal_kind="user",
            principal_id=owner_id,
            role="admin",
            scope_kind="space",
            scope_id=space.id,
        )
    )
    session.add(Membership(team_id=team.id, user_id=owner_id, role="owner"))
    session.flush()
    return team


def team_groups_for_user(session: Session, user_id: str) -> set[str]:
    """Return the ``team:{slug}`` groups the user gains from their Memberships.

    Resolved per-request from the ``memberships`` table (no caching) so removing
    a member immediately cuts their access — the next request sees no team group
    and the team-group grant no longer matches.
    """
    rows = (
        session.execute(
            select(Team.slug)
            .join(Membership, Membership.team_id == Team.id)
            .where(Membership.user_id == user_id)
        )
        .scalars()
        .all()
    )
    return {f"team:{slug}" for slug in rows}


def is_team_member(session: Session, team_id: uuid.UUID, user_id: str) -> bool:
    """True when ``user_id`` has a Membership in the given team.

    A direct membership check (not an RBAC grant walk): the authoritative gate
    for pushing knowledge into a team's private Space. Resolved per-request so a
    removed member is denied on their next call.
    """
    return (
        session.execute(
            select(Membership.id).where(
                Membership.team_id == team_id, Membership.user_id == user_id
            )
        ).first()
        is not None
    )
