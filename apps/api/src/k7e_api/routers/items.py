"""Items router: permission-aware retrieval of published knowledge items.

Endpoints:
    GET /items
        Returns a list of published KnowledgeItems (ItemSummary), ordered by
        updated_at descending. Filtered by allowed_item_ids when the
        authorization service restricts access.

    GET /items/{slug}
        Returns the full ItemDetail for a published item identified by slug.
        Returns 404 if the slug does not exist, is not published, or the
        principal is not allowed to access it.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from k7e_api.app_auth import get_effective_principal_with_teams
from k7e_api.auth import (
    AuthorizationService,
    Principal,
    Scope,
    get_authz,
    get_principal_with_teams,
)
from k7e_api.db import get_session
from k7e_api.lifecycle import archive_item
from k7e_api.models import ItemTag, KnowledgeItem, KnowledgeItemVersion, RawDocument
from k7e_api.okf import Domain, PageType
from k7e_api.personal_spaces import resolve_space_filter
from k7e_api.schemas import ItemDetail, ItemSummary
from k7e_api.spaces import space_refs_for
from k7e_api.tenancy import TenantContext, get_tenant_context, scoped

router = APIRouter()


def _resolve_provenance(session: Session, item: KnowledgeItem) -> list[dict]:
    """Resolve a KnowledgeItem's raw provenance refs into display entries.

    ``item.provenance`` holds ``{"resource": str|None, "source_pages": [slug]}``
    copied from OKF frontmatter. This turns it into a list of:
      - ``{"kind": "document", "raw_document_id", "label", "source_system"}``
        for the originating raw document (resolved via ``RawDocument.sha256``;
        an unmatched resource degrades to the raw string with a null id), and
      - ``{"kind": "page", "slug", "title"}`` for each source page a derived
        page was compiled from (title falls back to the slug if not found).
    """
    prov = item.provenance or {}
    entries: list[dict] = []

    resource = prov.get("resource")
    if resource:
        raw = (
            session.execute(
                select(RawDocument)
                .where(RawDocument.sha256 == resource)
                # sha256 is a content hash; identical re-uploads share it and
                # yield the same filename/source_system — take the most recent
                # as a deterministic tiebreaker.
                .order_by(RawDocument.created_at.desc())
            )
            .scalars()
            .first()
        )
        if raw is not None:
            entries.append(
                {
                    "kind": "document",
                    "raw_document_id": str(raw.id),
                    "label": raw.filename,
                    "source_system": raw.source_system,
                }
            )
        else:
            entries.append(
                {
                    "kind": "document",
                    "raw_document_id": None,
                    "label": resource,
                    "source_system": None,
                }
            )

    source_pages = prov.get("source_pages") or []
    if source_pages:
        rows = session.execute(
            select(KnowledgeItem.slug, KnowledgeItem.title).where(
                KnowledgeItem.slug.in_(source_pages)
            )
        ).all()
        title_by_slug = {slug: title for slug, title in rows}
        for slug in source_pages:
            entries.append(
                {
                    "kind": "page",
                    "slug": slug,
                    "title": title_by_slug.get(slug, slug),
                }
            )

    return entries


def _tags_for_items(session: Session, item_ids: list) -> dict:
    """Return ``{item_id: [tag, ...]}`` for the given items in one query."""
    if not item_ids:
        return {}
    rows = session.execute(
        select(ItemTag.item_id, ItemTag.tag).where(ItemTag.item_id.in_(item_ids))
    ).all()
    out: dict = {}
    for item_id, tag in rows:
        out.setdefault(item_id, []).append(tag)
    return out


@router.get("", response_model=list[ItemSummary])
def list_items(
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_effective_principal_with_teams)],
    authz: Annotated[AuthorizationService, Depends(get_authz)],
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    item_type: Annotated[
        PageType | None,
        Query(alias="type"),
    ] = None,
    domain: Annotated[Domain | None, Query()] = None,
    tags: Annotated[list[str] | None, Query(alias="tag")] = None,
    space: Annotated[str | None, Query(description="Space slug filter")] = None,
) -> list[ItemSummary]:
    """Return all published knowledge items the principal is allowed to see.

    Items are ordered by ``updated_at`` descending (most recently updated first).
    If ``authz.allowed_item_ids`` returns ``None`` (MVP default), all published
    items are returned without any ID filter.

    Args:
        item_type: Optional filter exposed as ``?type=``. When provided, only
            items with this exact type are returned. Must be one of
            ``"source"``, ``"entity"``, ``"concept"``, ``"analysis"`` — any
            other value yields a 422.
        domain: Optional filter exposed as ``?domain=``. When provided, only
            items with this exact domain are returned — any value outside the
            governed ``Domain`` set yields a 422.
        tags: Optional repeatable filter exposed as ``?tag=``. When provided,
            only items carrying *every* requested tag are returned (AND
            semantics across repeated ``?tag=`` params).
        space: Optional filter exposed as ``?space=``. Resolved org-scoped
            (``"personal"`` resolves to the caller's EXISTING personal space —
            never provisions one); an unresolved slug yields a 404. RBAC
            (``allowed_item_ids``) is applied independently — this filter
            only narrows that set, never widens it.

    Returns:
        List of :class:`~k7e_api.schemas.ItemSummary` objects.
    """
    space_id: uuid.UUID | None = None
    if space is not None:
        space_row = resolve_space_filter(
            session, space_slug=space, user_id=principal.user_id, org_id=ctx.org_id
        )
        if space_row is None:
            raise HTTPException(status_code=404, detail="Space not found")
        space_id = space_row.id

    allowed = authz.allowed_item_ids(principal, session)

    stmt = scoped(
        select(KnowledgeItem)
        .where(KnowledgeItem.status == "published")
        .where(KnowledgeItem.current_version_id.is_not(None))
        .order_by(KnowledgeItem.updated_at.desc()),
        ctx,
    )

    if allowed is not None:
        stmt = stmt.where(KnowledgeItem.id.in_(allowed))

    if item_type is not None:
        stmt = stmt.where(KnowledgeItem.type == item_type)

    if domain is not None:
        stmt = stmt.where(KnowledgeItem.domain == domain)
    if space_id is not None:
        stmt = stmt.where(KnowledgeItem.space_id == space_id)
    if tags:
        for tag in tags:
            stmt = stmt.where(
                KnowledgeItem.id.in_(
                    select(ItemTag.item_id).where(ItemTag.tag == tag.strip().lower())
                )
            )

    items = session.execute(stmt).scalars().all()
    tag_map = _tags_for_items(session, [item.id for item in items])
    space_map = space_refs_for([item.space_id for item in items], session)

    return [
        ItemSummary(
            id=item.id,
            slug=item.slug,
            title=item.title,
            status=item.status,
            type=item.type,
            domain=item.domain,
            tags=tag_map.get(item.id, []),
            updated_at=item.updated_at,
            space=space_map.get(item.space_id),
        )
        for item in items
    ]


@router.get("/{slug}", response_model=ItemDetail)
def get_item(
    slug: str,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_effective_principal_with_teams)],
    authz: Annotated[AuthorizationService, Depends(get_authz)],
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
) -> ItemDetail:
    """Return the full detail for the published item identified by *slug*.

    Args:
        slug: URL-safe slug of the item to retrieve.

    Returns:
        :class:`~k7e_api.schemas.ItemDetail` for the current version.

    Raises:
        HTTPException 404: If the item does not exist, is not published, or
            the principal is not in the allowed set.
    """
    # Fetch the item
    item: KnowledgeItem | None = session.execute(
        scoped(
            select(KnowledgeItem)
            .where(KnowledgeItem.slug == slug)
            .where(KnowledgeItem.status == "published")
            .where(KnowledgeItem.current_version_id.is_not(None)),
            ctx,
        )
    ).scalar_one_or_none()

    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    # Authorization check
    allowed = authz.allowed_item_ids(principal, session)
    if allowed is not None and item.id not in allowed:
        raise HTTPException(status_code=404, detail="Item not found")

    # Fetch current version
    version: KnowledgeItemVersion | None = session.get(
        KnowledgeItemVersion, item.current_version_id
    )
    if version is None:  # pragma: no cover – should not happen if DB is consistent
        raise HTTPException(status_code=404, detail="Item version not found")

    return ItemDetail(
        id=item.id,
        slug=item.slug,
        title=item.title,
        status=item.status,
        type=item.type,
        domain=item.domain,
        tags=_tags_for_items(session, [item.id]).get(item.id, []),
        updated_at=item.updated_at,
        markdown_body=version.markdown_body,
        version=version.version_number,
        citations=version.citations or [],
        model_id=version.model_id,
        sources=_resolve_provenance(session, item),
    )


@router.delete("/{slug}", response_model=ItemSummary)
def archive_item_endpoint(
    slug: str,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal_with_teams)],
    authz: Annotated[AuthorizationService, Depends(get_authz)],
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
) -> ItemSummary:
    """Soft-archive (retire) the published item identified by *slug*.

    The page transitions to ``status="archived"`` — it disappears from search,
    graph, and listings — and its graph/identity edges are detached. Versions
    are retained. Returns the archived item's summary.

    Raises:
        HTTPException 404: If the item does not exist, is not published, or the
            principal is not allowed to access it.
    """
    item: KnowledgeItem | None = session.execute(
        scoped(
            select(KnowledgeItem)
            .where(KnowledgeItem.slug == slug)
            .where(KnowledgeItem.status == "published")
            .where(KnowledgeItem.current_version_id.is_not(None)),
            ctx,
        )
    ).scalar_one_or_none()

    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    allowed = authz.allowed_item_ids(principal, session)
    if allowed is not None and item.id not in allowed:
        raise HTTPException(status_code=404, detail="Item not found")

    # Write gate: editor on the item's narrowest containment scope. The read
    # check above runs first, so an unauthorized reader gets 404 (not a
    # role-leaking 403) — only callers who can already read reach this gate.
    scope = (
        Scope("project", item.project_id)
        if item.project_id is not None
        else Scope("space", item.space_id)
        if item.space_id is not None
        else Scope("org", item.org_id)
    )
    if not authz.can_write(principal, scope):
        raise HTTPException(status_code=403, detail="Editor role required")

    archive_item(session, item)
    session.commit()

    return ItemSummary(
        id=item.id,
        slug=item.slug,
        title=item.title,
        status=item.status,
        type=item.type,
        domain=item.domain,
        tags=_tags_for_items(session, [item.id]).get(item.id, []),
        updated_at=item.updated_at,
    )
