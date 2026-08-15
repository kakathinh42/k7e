"""Facets router: permission-scoped classification facets for discovery.

GET /facets returns the domains, tags, and page types present in the caller's
visible, published corpus, each with a count — the payload the Web discovery
UI renders as filter chips. Counts are computed strictly over
``allowed_item_ids ∩ scoped(published)`` so a principal never sees a count that
includes a page they cannot read. Tags are capped to the top ``TAG_FACET_LIMIT``
by count (documented, not silently truncated).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from k7e_api.app_auth import get_effective_principal_with_teams
from k7e_api.auth import (
    AuthorizationService,
    Principal,
    get_authz,
)
from k7e_api.db import get_session
from k7e_api.models import ItemTag, KnowledgeItem
from k7e_api.schemas import FacetCount, FacetsResponse
from k7e_api.tenancy import TenantContext, get_tenant_context, scoped

router = APIRouter()

#: Max number of tag facets returned (highest-count first). Documented cap.
TAG_FACET_LIMIT = 50


@router.get("", response_model=FacetsResponse)
def get_facets(
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_effective_principal_with_teams)],
    authz: Annotated[AuthorizationService, Depends(get_authz)],
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
) -> FacetsResponse:
    """Return permission-scoped domain/tag/type facet counts."""
    allowed = authz.allowed_item_ids(principal, session)

    id_stmt = scoped(
        select(KnowledgeItem.id)
        .where(KnowledgeItem.status == "published")
        .where(KnowledgeItem.current_version_id.is_not(None)),
        ctx,
    )
    if allowed is not None:
        id_stmt = id_stmt.where(KnowledgeItem.id.in_(allowed))
    allowed_ids = session.execute(id_stmt).scalars().all()

    if not allowed_ids:
        return FacetsResponse(domains=[], tags=[], types=[])

    domain_rows = session.execute(
        select(KnowledgeItem.domain, func.count())
        .where(KnowledgeItem.id.in_(allowed_ids))
        .where(KnowledgeItem.domain.is_not(None))
        .group_by(KnowledgeItem.domain)
        .order_by(func.count().desc(), KnowledgeItem.domain)
    ).all()

    type_rows = session.execute(
        select(KnowledgeItem.type, func.count())
        .where(KnowledgeItem.id.in_(allowed_ids))
        .group_by(KnowledgeItem.type)
        .order_by(func.count().desc(), KnowledgeItem.type)
    ).all()

    tag_rows = session.execute(
        select(ItemTag.tag, func.count())
        .where(ItemTag.item_id.in_(allowed_ids))
        .group_by(ItemTag.tag)
        .order_by(func.count().desc(), ItemTag.tag)
        .limit(TAG_FACET_LIMIT)
    ).all()

    return FacetsResponse(
        domains=[FacetCount(value=v, count=c) for v, c in domain_rows],
        tags=[FacetCount(value=v, count=c) for v, c in tag_rows],
        types=[FacetCount(value=v, count=c) for v, c in type_rows],
    )
