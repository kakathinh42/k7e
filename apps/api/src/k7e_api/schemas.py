"""Pydantic v2 schemas for k7e API request/response models."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

# SearchHit is defined in search.py; import here for use in SearchResponse.
# Imported inside the class or at module level – we use module-level import
# since there is no circular dependency: schemas.py does NOT import from
# routers, and search.py does NOT import from schemas.py.
from k7e_api.search import SearchHit  # noqa: F401 – re-exported for convenience


class UploadResponse(BaseModel):
    """Response body returned by POST /ingest/upload."""

    workflow_id: str
    raw_document_id: uuid.UUID


# ---------------------------------------------------------------------------
# Item response schemas (Task 3.3)
# ---------------------------------------------------------------------------


class SpaceRef(BaseModel):
    """Which space a page lives in, plus its user-facing kind.

    ``kind`` is one of ``personal`` (a user's private space), ``team`` (owned by
    a Team), or ``public`` (the shared org corpus). Computed by
    ``k7e_api.spaces.space_kind`` — the frontend never re-derives it.
    """

    slug: str
    name: str
    kind: str


class ItemSummary(BaseModel):
    """Compact summary of a published knowledge item (used in GET /items list).

    Attributes:
        id: UUID primary key of the ``KnowledgeItem``.
        slug: URL-safe slug.
        title: Human-readable title.
        status: Publication status (always "published" in list responses).
        updated_at: When the item was last updated.
        space: Which space the page lives in (slug/name/kind), or None.
    """

    id: uuid.UUID
    slug: str
    title: str
    status: str
    type: str
    domain: str | None = None
    tags: list[str] = []
    updated_at: datetime
    space: SpaceRef | None = None


class ItemDetail(ItemSummary):
    """Full detail of a published knowledge item (used in GET /items/{slug}).

    Extends :class:`ItemSummary` with the full content fields from the current
    version.

    Attributes:
        markdown_body: The full Markdown text of the current version.
        version: The version number of the current version.
        citations: List of citation dicts ``{"raw_document_id": ..., "quote": ...}``.
        model_id: Identifier of the LLM model that produced this version.
        sources: Resolved provenance entries, each either
            ``{"kind": "document", "raw_document_id", "label", "source_system"}``
            (the originating raw document of a source page) or
            ``{"kind": "page", "slug", "title"}`` (a source page that a derived
            page was compiled from). Empty when no provenance is recorded.
    """

    markdown_body: str
    version: int
    citations: list[dict]
    model_id: str
    sources: list[dict] = []


# ---------------------------------------------------------------------------
# Search response schemas (Task 3.3)
# ---------------------------------------------------------------------------


class SearchResponse(BaseModel):
    """Response body for GET /search.

    Attributes:
        hits: Ordered list of search results.
    """

    hits: list[SearchHit]


# ---------------------------------------------------------------------------
# Knowledge-graph schemas (GET /graph)
# ---------------------------------------------------------------------------


class GraphNode(BaseModel):
    """A published page rendered as a graph node.

    Attributes:
        id: UUID of the ``KnowledgeItem``.
        slug: URL-safe slug (stable label).
        title: Human-readable title.
        degree: Number of distinct related pages (undirected edge count) — a
            convenient size/importance hint for visualisations.
    """

    id: uuid.UUID
    slug: str
    title: str
    degree: int


class GraphEdge(BaseModel):
    """An undirected ``related`` edge between two pages.

    The underlying ``wiki_links`` rows are stored symmetrically (A→B and B→A);
    this schema collapses each pair to a single edge for rendering.

    Attributes:
        source: UUID of one endpoint.
        target: UUID of the other endpoint.
        score: Similarity that produced the edge (0..1; 1.0 for explicit links).
        relation: Edge type (currently always ``"related"``).
        origin: ``"vector"`` (similarity-derived) or ``"explicit"`` (author
            ``[[wikilink]]``). A pair connected by both is reported as
            ``"explicit"``.
    """

    source: uuid.UUID
    target: uuid.UUID
    score: float
    relation: str
    origin: str


class GraphResponse(BaseModel):
    """Response body for GET /graph — the permission-filtered knowledge graph."""

    nodes: list[GraphNode]
    edges: list[GraphEdge]


# ---------------------------------------------------------------------------
# Facet schemas (GET /facets) — M4 faceted discovery
# ---------------------------------------------------------------------------


class FacetCount(BaseModel):
    """One facet value and how many visible published items carry it."""

    value: str
    count: int


class FacetsResponse(BaseModel):
    """Available classification facets (with counts) over the visible corpus."""

    domains: list[FacetCount]
    tags: list[FacetCount]
    types: list[FacetCount]


# ---------------------------------------------------------------------------
# Connector schemas (M5 — POST /connectors/{space_slug}/sync)
# ---------------------------------------------------------------------------


class ConnectorSyncResult(BaseModel):
    """Response for POST /connectors/{space_slug}/sync."""

    connector: str
    ingested: int
    skipped: int


# ---------------------------------------------------------------------------
# App schemas (M6 — POST/GET /apps: org-admin ClientApp provisioning)
# ---------------------------------------------------------------------------


class AppCreate(BaseModel):
    slug: str
    name: str


class AppSummary(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    org_id: uuid.UUID
    created_at: datetime


class AppOut(AppSummary):
    """Provisioning response — carries the plaintext key ONCE."""

    api_key: str


# ---------------------------------------------------------------------------
# Source ingest schemas (M6 — POST /ingest/source: app ingests as itself)
# ---------------------------------------------------------------------------


class SourceIngestRequest(BaseModel):
    source_system: str
    source_external_id: str
    source_tier: str = "A"
    content: str
    content_type: str = "text/markdown"
    allowed_groups: list[str] | None = None


class SourceIngestResponse(BaseModel):
    status: str  # "ingested" | "skipped"
    raw_document_id: str
    workflow_id: str | None = None
