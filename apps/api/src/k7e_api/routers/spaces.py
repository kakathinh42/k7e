"""Spaces router: GET /spaces — the caller's accessible spaces with counts.

Single source for the web app's space tabs, home breakdown, and Spaces page.
Admission mirrors GET /items (same ``allowed_item_ids``), so no space the
caller can't read ever appears; the caller's own personal space is always
included (even when empty) so "where do my saves go" is always answerable.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from k7e_api.app_auth import get_effective_principal_with_teams
from k7e_api.auth import AuthorizationService, Principal, get_authz
from k7e_api.db import get_session
from k7e_api.models import KnowledgeItem, Space
from k7e_api.personal_spaces import personal_space_for
from k7e_api.spaces import space_kind
from k7e_api.tenancy import TenantContext, get_tenant_context, scoped

router = APIRouter()


class SpaceSummary(BaseModel):
    """A space the caller can read, plus its kind and published-item count."""

    slug: str
    name: str
    kind: str
    item_count: int


@router.get("", response_model=list[SpaceSummary])
def list_spaces(
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_effective_principal_with_teams)],
    authz: Annotated[AuthorizationService, Depends(get_authz)],
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
) -> list[SpaceSummary]:
    """List the spaces the caller can read, with counts, ordered by count desc."""
    allowed = authz.allowed_item_ids(principal, session)

    stmt = scoped(
        select(KnowledgeItem.space_id, func.count(KnowledgeItem.id))
        .where(KnowledgeItem.status == "published")
        .where(KnowledgeItem.current_version_id.is_not(None))
        .where(KnowledgeItem.space_id.is_not(None))
        .group_by(KnowledgeItem.space_id),
        ctx,
    )
    if allowed is not None:
        stmt = stmt.where(KnowledgeItem.id.in_(allowed))

    counts: dict[uuid.UUID, int] = {space_id: n for space_id, n in session.execute(stmt).all()}

    # Always include the caller's own personal space (may have 0 items).
    if principal.user_id and principal.user_id not in ("", "anonymous"):
        personal = personal_space_for(session, user_id=principal.user_id, org_id=ctx.org_id)
        if personal is not None:
            counts.setdefault(personal.id, 0)

    if not counts:
        return []

    spaces = (
        session.execute(select(Space).where(Space.id.in_(list(counts.keys())))).scalars().all()
    )
    out = [
        SpaceSummary(
            slug=sp.slug,
            name=sp.name,
            kind=space_kind(sp, session),
            item_count=counts.get(sp.id, 0),
        )
        for sp in spaces
    ]
    out.sort(key=lambda s: s.item_count, reverse=True)
    return out
