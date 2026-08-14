"""Graph router: permission-aware read of the page-to-page knowledge graph.

Endpoint:
    GET /graph
        Returns the ``related`` graph over published knowledge items the
        principal may see: nodes (pages) + undirected edges (vector-similarity
        ``wiki_links``). Edges are filtered so BOTH endpoints are visible, and
        the symmetric A->B / B->A rows are collapsed to one edge.

The shape ({nodes, edges}) is intended to drop straight into a force-directed
viewer (vis-network, d3-force, cytoscape) with no transformation.
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
    get_authz,
)
from k7e_api.db import get_session
from k7e_api.models import ItemTag, KnowledgeItem, WikiLink
from k7e_api.okf import Domain
from k7e_api.personal_spaces import resolve_space_filter
from k7e_api.schemas import GraphEdge, GraphNode, GraphResponse
from k7e_api.tenancy import TenantContext, get_tenant_context, scoped

router = APIRouter()


@router.get("", response_model=GraphResponse)
def get_graph(
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_effective_principal_with_teams)],
    authz: Annotated[AuthorizationService, Depends(get_authz)],
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    min_score: Annotated[float, Query(ge=0.0, le=1.0)] = 0.0,
    domain: Annotated[Domain | None, Query()] = None,
    tags: Annotated[list[str] | None, Query(alias="tag")] = None,
    space: Annotated[str | None, Query(description="Space slug filter")] = None,
) -> GraphResponse:
    """Return the permission-filtered ``related`` knowledge graph.

    Args:
        min_score: Drop edges whose similarity score is below this floor
            (default 0.0 = keep all). Handy for de-cluttering dense graphs.
        domain: Optional filter exposed as ``?domain=``. When provided, only
            items with this exact domain become nodes — any value outside the
            governed ``Domain`` set yields a 422. Edges with a filtered-out
            endpoint are dropped.
        tags: Optional repeatable filter exposed as ``?tag=``. When provided,
            only items carrying *every* requested tag become nodes (AND
            semantics across repeated ``?tag=`` params).
        space: Optional filter exposed as ``?space=`` — restrict the graph to a
            single space (``"personal"`` resolves to the caller's existing
            personal space; any other slug is an org-scoped lookup, 404 if
            absent). RBAC is applied independently and only narrows the set.

    Returns:
        :class:`~k7e_api.schemas.GraphResponse` with ``nodes`` and ``edges``.
        Only published items with a current version are included; an edge is
        returned only when both of its endpoints are in that visible set.
    """
    # Resolve an optional ``space=`` filter (personal / team / public) so the
    # graph can be viewed one space at a time — mirrors ``/items``. RBAC
    # (``allowed_item_ids``) is applied independently and only ever narrows.
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
        .where(KnowledgeItem.current_version_id.is_not(None)),
        ctx,
    )
    if allowed is not None:
        stmt = stmt.where(KnowledgeItem.id.in_(allowed))

    if space_id is not None:
        stmt = stmt.where(KnowledgeItem.space_id == space_id)

    if domain is not None:
        stmt = stmt.where(KnowledgeItem.domain == domain)
    if tags:
        for tag in tags:
            stmt = stmt.where(
                KnowledgeItem.id.in_(
                    select(ItemTag.item_id).where(ItemTag.tag == tag.strip().lower())
                )
            )

    items = session.execute(stmt).scalars().all()

    node_ids = {item.id for item in items}
    if not node_ids:
        return GraphResponse(nodes=[], edges=[])

    # Collapse edges to one undirected edge per pair, keeping only edges whose
    # endpoints are both visible and above the floor. Both vector (symmetric)
    # and explicit (directional) edges are included; when a pair has both, the
    # explicit origin wins (author intent dominates derived similarity).
    links = (
        session.execute(select(WikiLink).where(WikiLink.source_item_id.in_(node_ids)))
        .scalars()
        .all()
    )
    edges: list[GraphEdge] = []
    degree: dict = {nid: 0 for nid in node_ids}
    by_pair: dict[frozenset, GraphEdge] = {}
    for link in links:
        src, tgt = link.source_item_id, link.target_item_id
        if src not in node_ids or tgt not in node_ids:
            continue
        if link.score < min_score:
            continue
        pair = frozenset((src, tgt))
        existing = by_pair.get(pair)
        if existing is None:
            edge = GraphEdge(
                source=src,
                target=tgt,
                score=link.score,
                relation=link.relation,
                origin=link.origin,
            )
            by_pair[pair] = edge
            edges.append(edge)
            degree[src] += 1
            degree[tgt] += 1
        elif link.origin == "explicit":
            # Upgrade an existing vector edge to explicit (keep stronger score).
            existing.origin = "explicit"
            existing.score = max(existing.score, link.score)

    nodes = [
        GraphNode(id=item.id, slug=item.slug, title=item.title, degree=degree[item.id])
        for item in items
    ]
    return GraphResponse(nodes=nodes, edges=edges)
