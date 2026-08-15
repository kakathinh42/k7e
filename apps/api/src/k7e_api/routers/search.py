"""Search router: permission-aware hybrid search over published items.

Endpoints:
    GET /search?q=<text>&limit=20
        Executes a hybrid (keyword + vector + recency) search and returns
        matching published items, filtered by the principal's allowed item
        IDs. The search response is timed using the RETRIEVAL_LATENCY
        Prometheus histogram.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from k7e_api.app_auth import get_effective_principal_with_teams
from k7e_api.auth import (
    AuthorizationService,
    Principal,
    get_authz,
)
from k7e_api.config import get_settings
from k7e_api.db import get_session
from k7e_api.deps import get_embedding_client
from k7e_api.embedding_client import EmbeddingClient
from k7e_api.logging_setup import get_logger
from k7e_api.metrics import RETRIEVAL_LATENCY
from k7e_api.okf import Domain
from k7e_api.personal_spaces import resolve_space_filter
from k7e_api.schemas import SearchResponse
from k7e_api.search import SearchProvider, get_search_provider
from k7e_api.tenancy import TenantContext, get_tenant_context

router = APIRouter()


@router.get("", response_model=SearchResponse)
async def search_items(
    q: Annotated[str, Query(description="Search query text")] = "",
    limit: Annotated[int, Query(ge=1, le=100, description="Max results")] = 20,
    domain: Annotated[Domain | None, Query()] = None,
    tags: Annotated[list[str] | None, Query(alias="tag")] = None,
    spaces: Annotated[
        list[str] | None,
        Query(alias="space", description="Space slug filter (repeatable → union)"),
    ] = None,
    explain: Annotated[bool, Query(description="Include per-hit score breakdown")] = False,
    session: Annotated[Session, Depends(get_session)] = None,
    principal: Annotated[Principal, Depends(get_effective_principal_with_teams)] = None,
    authz: Annotated[AuthorizationService, Depends(get_authz)] = None,
    provider: Annotated[SearchProvider, Depends(get_search_provider)] = None,
    embedder: Annotated[EmbeddingClient, Depends(get_embedding_client)] = None,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)] = None,
) -> SearchResponse:
    """Search published knowledge items using hybrid (keyword + vector + recency) search.

    The query is embedded via the configured embedding client before being
    passed to the search provider for blended ranking across keyword
    presence, vector similarity, and recency. The search response is timed
    using the RETRIEVAL_LATENCY Prometheus histogram.

    Args:
        q: Query string (empty query returns no hits).
        limit: Maximum number of results (1–100, default 20).
        spaces: Optional filter exposed as a repeatable ``?space=`` — results are
            the **union** across the named spaces. Each slug is resolved
            org-scoped (``"personal"`` resolves to the caller's EXISTING personal
            space — never provisions one); an unresolved slug yields a 404. RBAC
            is applied independently via ``allowed_ids`` — this filter only
            narrows that set, it never widens what the caller can see.

    Returns:
        :class:`~k7e_api.schemas.SearchResponse` with ``hits`` list.
    """
    space_ids: list[uuid.UUID] | None = None
    if spaces:
        resolved: list[uuid.UUID] = []
        for slug in spaces:
            space_row = resolve_space_filter(
                session, space_slug=slug, user_id=principal.user_id, org_id=ctx.org_id
            )
            if space_row is None:
                raise HTTPException(status_code=404, detail=f"Space not found: {slug}")
            resolved.append(space_row.id)
        space_ids = resolved

    if not q:
        return SearchResponse(hits=[])

    allowed = authz.allowed_item_ids(principal, session)
    # Score breakdown is a transparency feature — available to any caller who
    # opts in via ?explain=true (it only annotates hits the caller can already see).
    explain_ok = explain

    # Best-effort: embeddings add the vector signal, but search must still work
    # (keyword + recency) when they are disabled or the endpoint rate-limits.
    # An empty query embedding makes every vector cosine 0.0 -> keyword-only rank.
    query_embedding: list[float] = []
    if get_settings().embeddings_enabled:
        try:
            (query_embedding,) = await embedder.embed([q])
        except Exception as exc:  # noqa: BLE001 - degrade, don't 500
            get_logger(__name__).warning("search_embed_failed", error=str(exc))

    with RETRIEVAL_LATENCY.time():
        hits = provider.query(
            text=q,
            query_embedding=query_embedding,
            allowed_ids=allowed,
            limit=limit,
            session=session,
            ctx=ctx,
            domain=domain,
            tags=tags,
            space_ids=space_ids,
            explain=explain_ok,
        )

    return SearchResponse(hits=hits)
