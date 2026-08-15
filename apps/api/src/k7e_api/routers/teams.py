"""Teams router: create teams, manage members (M3 Step A).

POST   /teams                       — any authenticated caller → becomes owner.
GET    /teams                       — member-scoped, org-scoped list of caller's teams.
GET    /teams/{slug}                 — member-gated (returns team + members).
POST   /teams/{slug}/members         — owner/admin (can_admin) adds a member.
DELETE /teams/{slug}/members/{user_id} — owner/admin removes a member.

All org-scoped via get_tenant_context. ``can_admin`` (RBAC: user admin grant at
the team space) gates mutations; the owner is seeded with that grant by
provision_team. Adding an ``admin``-role member also seeds a user admin grant;
removing a member drops their membership AND any user admin grant at the team
space (so removal fully cuts both management rights and grant-derived access).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from k7e_api.auth import (
    AuthorizationService,
    Principal,
    Scope,
    get_authz,
    get_principal,
)
from k7e_api.db import get_session
from k7e_api.models import Membership, RoleGrant, Team
from k7e_api.teams import ReservedSlugError, is_team_member, provision_team
from k7e_api.tenancy import TenantContext, get_tenant_context

router = APIRouter()

_VALID_MEMBER_ROLES = {"owner", "admin", "member", "viewer"}


class TeamCreate(BaseModel):
    slug: str
    name: str


class MemberAdd(BaseModel):
    user_id: str
    role: str = "member"  # owner|admin|member|viewer


class MemberOut(BaseModel):
    user_id: str
    role: str
    created_at: datetime


class TeamOut(BaseModel):
    id: str
    slug: str
    name: str
    org_id: str
    space_id: str
    created_by: str
    created_at: datetime
    members: list[MemberOut]


def _team_or_404(session: Session, org_id: uuid.UUID, slug: str) -> Team:
    team = session.execute(
        select(Team).where(Team.org_id == org_id, Team.slug == slug)
    ).scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


def _is_member(session: Session, team_id: uuid.UUID, user_id: str) -> bool:
    return is_team_member(session, team_id, user_id)


def _to_team_out(session: Session, team: Team) -> TeamOut:
    members = (
        session.execute(select(Membership).where(Membership.team_id == team.id)).scalars().all()
    )
    return TeamOut(
        id=str(team.id),
        slug=team.slug,
        name=team.name,
        org_id=str(team.org_id),
        space_id=str(team.space_id),
        created_by=team.created_by,
        created_at=team.created_at,
        members=[
            MemberOut(user_id=m.user_id, role=m.role, created_at=m.created_at) for m in members
        ],
    )


@router.post("", response_model=TeamOut, status_code=status.HTTP_201_CREATED)
def create_team(
    body: TeamCreate,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
) -> TeamOut:
    """Create a team. The caller becomes the owner."""
    try:
        team = provision_team(
            session,
            slug=body.slug,
            name=body.name,
            owner_id=principal.user_id,
            org_id=ctx.org_id,
        )
        session.commit()
    except ReservedSlugError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="Team slug already exists")
    return _to_team_out(session, team)


@router.get("", response_model=list[TeamOut])
def list_teams(
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
) -> list[TeamOut]:
    """List teams the caller is a member of, scoped to the current org."""
    teams = (
        session.execute(
            select(Team)
            .join(Membership, Membership.team_id == Team.id)
            .where(
                Team.org_id == ctx.org_id,
                Membership.user_id == principal.user_id,
            )
            .order_by(Team.created_at)
        )
        .scalars()
        .all()
    )
    return [_to_team_out(session, t) for t in teams]


@router.get("/{slug}", response_model=TeamOut)
def get_team(
    slug: str,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
) -> TeamOut:
    """Return a team + its members. Members only (hide existence from non-members)."""
    team = _team_or_404(session, ctx.org_id, slug)
    if not _is_member(session, team.id, principal.user_id):
        raise HTTPException(status_code=404, detail="Team not found")
    return _to_team_out(session, team)


@router.post("/{slug}/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
def add_member(
    slug: str,
    body: MemberAdd,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    authz: Annotated[AuthorizationService, Depends(get_authz)],
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
) -> MemberOut:
    """Add a member. Owner/admin only (can_admin at the team space)."""
    team = _team_or_404(session, ctx.org_id, slug)
    if not authz.can_admin(principal, Scope("space", team.space_id)):
        raise HTTPException(status_code=403, detail="Admin role required")
    if body.role not in _VALID_MEMBER_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    if _is_member(session, team.id, body.user_id):
        raise HTTPException(status_code=409, detail="Already a member")
    membership = Membership(team_id=team.id, user_id=body.user_id, role=body.role)
    session.add(membership)
    if body.role == "admin":
        session.add(
            RoleGrant(
                principal_kind="user",
                principal_id=body.user_id,
                role="admin",
                scope_kind="space",
                scope_id=team.space_id,
            )
        )
    session.commit()
    return MemberOut(
        user_id=membership.user_id,
        role=membership.role,
        created_at=membership.created_at,
    )


@router.delete("/{slug}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    slug: str,
    user_id: str,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    authz: Annotated[AuthorizationService, Depends(get_authz)],
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
) -> None:
    """Remove a member. Owner/admin only. Cuts access immediately (per-request)."""
    team = _team_or_404(session, ctx.org_id, slug)
    if not authz.can_admin(principal, Scope("space", team.space_id)):
        raise HTTPException(status_code=403, detail="Admin role required")
    membership = session.execute(
        select(Membership).where(Membership.team_id == team.id, Membership.user_id == user_id)
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=404, detail="Member not found")
    session.delete(membership)
    # Drop any user admin grant at this space for the removed user so removal
    # fully cuts both management rights and grant-derived read access.
    grant = session.execute(
        select(RoleGrant).where(
            RoleGrant.principal_kind == "user",
            RoleGrant.principal_id == user_id,
            RoleGrant.role == "admin",
            RoleGrant.scope_kind == "space",
            RoleGrant.scope_id == team.space_id,
        )
    ).scalar_one_or_none()
    if grant is not None:
        session.delete(grant)
    session.commit()
