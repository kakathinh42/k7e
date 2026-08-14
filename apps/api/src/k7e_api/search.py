"""Search provider abstraction and hybrid implementation.

Defines:
- ``SearchHit``: a single search result with id, slug, title, snippet, score.
- ``SearchProvider``: a Protocol describing the search contract.
- ``HybridSearchProvider``: keyword + vector + recency blend with a relevance
  gate implemented in Python (no pgvector required).
- ``get_search_provider``: FastAPI dependency.

Design notes
------------
* ``SearchHit`` is defined here (not in ``schemas.py``) to keep search domain
  logic self-contained.  ``schemas.py`` imports ``SearchHit`` from here for
  the ``SearchResponse`` model.
* The search implementation queries published ``KnowledgeItem``s (status ==
  "published" and current_version_id IS NOT NULL).
* Relevance gate: an item is kept iff ``keyword_score > 0`` OR
  ``vector_score >= settings.search_min_vector_similarity``.
* Blended score: ``w_kw * keyword + w_vec * vector + w_rec * recency``,
  where recency uses exponential decay based on ``item.updated_at``.
* ``selectinload(KnowledgeItemVersion.chunks)`` avoids N+1 queries.
* ``allowed_ids`` filter: when not ``None``, restricts to the given set via
  ``KnowledgeItem.id.in_(allowed_ids)``.
* ``ctx`` (TenantContext): when provided, restricts to the tenant's org via
  ``scoped()``. Passing ``None`` skips org-scoping (used in unit tests that
  call the provider directly without a FastAPI request context).
"""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session, selectinload

from k7e_api.config import get_settings
from k7e_api.graph import cosine
from k7e_api.models import ItemTag, KnowledgeItem, KnowledgeItemVersion, WikiLink
from k7e_api.tenancy import TenantContext, scoped


def _vector_similarity_map(
    session: Session,
    query_embedding: list[float],
    version_ids: list[uuid.UUID],
) -> dict | None:
    """Best cosine similarity per version, computed by pgvector on PostgreSQL.

    Returns ``{version_id: similarity}`` on PostgreSQL (similarity = 1 - the
    indexed ``<=>`` cosine distance), or ``None`` on any other dialect so the
    caller falls back to the in-Python computation. Returns an empty map when
    there is nothing to score (no versions, or an empty query embedding — the
    keyword-only degradation path), which keeps every vector score at 0.0.
    """
    if session.get_bind().dialect.name != "postgresql":
        return None
    if not query_embedding or not version_ids:
        return {}
    vec_literal = "[" + ",".join(repr(float(x)) for x in query_embedding) + "]"
    rows = session.execute(
        sa_text(
            "SELECT version_id, COALESCE(MAX(1 - (embedding <=> (:q)::vector)), 0.0) AS sim "
            "FROM wiki_chunks WHERE version_id = ANY(:ids) AND embedding IS NOT NULL "
            "GROUP BY version_id"
        ),
        {"q": vec_literal, "ids": list(version_ids)},
    )
    return {vid: float(sim) for vid, sim in rows}


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------

_SNIPPET_MAX_LEN = 160
_WORD_RE = re.compile(r"[a-z0-9]+")
# CJK runs (hiragana, katakana, CJK ideographs incl. ext-A + compat, Hangul).
# These scripts have no spaces between words, so ``_WORD_RE`` yields nothing for
# them — keyword search would miss all Japanese/Chinese/Korean content. We index
# CJK as character bigrams (e.g. 審査 -> 審, 査) for substring-ish matching.
_CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯豈-﫿]+")


def _tokenize(text: str) -> set[str]:
    """Lexical tokens for keyword matching: ASCII words + CJK character bigrams."""
    text = text.lower()
    tokens: set[str] = set(_WORD_RE.findall(text))
    for run in _CJK_RE.findall(text):
        if len(run) == 1:
            tokens.add(run)
        else:
            tokens.update(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


class ScoreBreakdown(BaseModel):
    """Per-hit ranking explanation (populated only under explain mode)."""

    total: float
    # Direct-hit signals (None for graph-expanded hits).
    keyword: float | None = None
    vector: float | None = None
    recency: float | None = None
    importance: float | None = None
    weights: dict[str, float] | None = None
    # Graph-expanded-hit fields (expanded=True).
    expanded: bool = False
    via: str | None = None
    edge_score: float | None = None
    parent_score: float | None = None
    decay: float | None = None


class SearchHit(BaseModel):
    """A single result from a search query.

    Attributes:
        id: UUID of the ``KnowledgeItem``.
        slug: URL-safe slug of the item.
        title: Human-readable title.
        snippet: First ~160 chars of ``markdown_body`` for display.
        score: Relevance score (blended keyword + vector + recency).
    """

    id: uuid.UUID
    slug: str
    title: str
    snippet: str
    score: float
    breakdown: ScoreBreakdown | None = None


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class SearchProvider(Protocol):
    """Contract for search backends."""

    def query(
        self,
        text: str,
        query_embedding: list[float],
        allowed_ids: set[uuid.UUID] | None,
        limit: int,
        session: Session,
        ctx: TenantContext | None = None,
        domain: str | None = None,
        tags: list[str] | None = None,
        space_ids: list[uuid.UUID] | None = None,
    ) -> list[SearchHit]:
        """Execute a search and return ordered hits.

        Args:
            text: The query string to search for.
            query_embedding: The embedding vector for ``text``.
            allowed_ids: When not ``None``, restrict results to these item UUIDs.
            limit: Maximum number of results to return.
            session: An open SQLAlchemy session.
            ctx: Tenant context for org-scoping. When ``None``, no org predicate
                is applied (used in unit tests that call the provider directly).
            domain: When not ``None``, restrict results to items in this domain.
            tags: When not empty, restrict results to items carrying every tag.
            space_ids: When not empty, restrict results to items in any of these
                spaces (union).

        Returns:
            A list of :class:`SearchHit` objects, at most ``limit`` long.
        """
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_snippet(markdown_body: str, max_len: int = _SNIPPET_MAX_LEN) -> str:
    """Return the first *max_len* characters of *markdown_body*.

    Tries to truncate at a word boundary (last space before the limit) to
    avoid splitting mid-word.
    """
    if len(markdown_body) <= max_len:
        return markdown_body
    truncated = markdown_body[:max_len]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        truncated = truncated[:last_space]
    return truncated + "…"


def _build_breakdown(sc: _Scored, s) -> ScoreBreakdown:
    """Turn a ranked _Scored into its explain-mode breakdown."""
    if sc.via_slug is not None:
        return ScoreBreakdown(
            total=sc.score,
            expanded=True,
            via=sc.via_slug,
            edge_score=sc.edge_score,
            parent_score=sc.parent_score,
            decay=sc.decay,
        )
    return ScoreBreakdown(
        total=sc.score,
        keyword=sc.kw,
        vector=sc.vec,
        recency=sc.rec,
        importance=sc.importance,
        weights={
            "keyword": s.search_w_keyword,
            "vector": s.search_w_vector,
            "recency": s.search_w_recency,
            "importance": s.search_w_importance,
        },
    )


def _keyword_score(query: str, *texts: str) -> float:
    """Return fraction of query terms found in the concatenated texts."""
    terms = _tokenize(query)
    if not terms:
        return 0.0
    hay_terms = _tokenize(" ".join(texts))
    return sum(1 for t in terms if t in hay_terms) / len(terms)


def _degree_map(session: Session, item_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Return {item_id: out-degree} from wiki_links for the given items."""
    if not item_ids:
        return {}
    rows = session.execute(
        select(WikiLink.source_item_id, func.count())
        .where(WikiLink.source_item_id.in_(item_ids))
        .group_by(WikiLink.source_item_id)
    ).all()
    return {iid: n for iid, n in rows}


@dataclass
class _Scored:
    """A ranked candidate that carries its component scores for explain mode."""

    score: float
    item: KnowledgeItem
    version: KnowledgeItemVersion
    kw: float = 0.0
    vec: float = 0.0
    rec: float = 0.0
    importance: float = 0.0
    # Set only for graph-expanded hits.
    via_slug: str | None = None
    edge_score: float | None = None
    parent_score: float | None = None
    decay: float | None = None


def _expand(
    session: Session,
    ranked: list[_Scored],
    existing_ids: set[uuid.UUID],
    settings,
    allowed_ids: set[uuid.UUID] | None = None,
    ctx: TenantContext | None = None,
    domain: str | None = None,
    tags: list[str] | None = None,
    space_ids: list[uuid.UUID] | None = None,
) -> list[_Scored]:
    """Return extra _Scored for 1-hop neighbours of the top hits.

    Neighbour items are loaded in a single bulk query (not one query per target)
    to avoid N×M round-trips on the hot search path.
    """
    seen = set(existing_ids)

    # Phase 1: collect all (parent_score, edge_score, target_id) across the
    # top hits, deduplicating targets that appear in multiple hit neighbourhoods.
    # NOTE: The WikiLink edge query below is NOT org-scoped — links don't carry
    # a useful predicate here because what matters is whether the TARGET item is
    # accessible, not the edge itself. Org isolation is enforced in Phase 2 where
    # the neighbour items are loaded through scoped(). A cross-tenant edge can
    # be traversed but its target will be filtered out in the item-load step.
    candidates: list[tuple[float, float, uuid.UUID, str]] = []
    for parent in ranked[: settings.graph_expand_top_hits]:
        parent_score, parent_item = parent.score, parent.item
        edges = session.execute(
            select(WikiLink.target_item_id, WikiLink.score)
            .where(WikiLink.source_item_id == parent_item.id)
            .where(WikiLink.origin.in_(("vector", "explicit")))
            .order_by(WikiLink.score.desc())
            .limit(settings.graph_expand_per_hit)
        ).all()
        for target_id, edge_score in edges:
            if target_id not in seen:
                seen.add(target_id)
                candidates.append((parent_score, edge_score, target_id, parent_item.slug))

    if not candidates:
        return []

    # Phase 2: batch-load all neighbour items in one query. Permission-filtered:
    # expansion must not surface neighbours the caller cannot access.
    target_ids = [t for _, _, t, _ in candidates]
    stmt = (
        select(KnowledgeItem, KnowledgeItemVersion)
        .join(
            KnowledgeItemVersion,
            KnowledgeItem.current_version_id == KnowledgeItemVersion.id,
        )
        .where(KnowledgeItem.id.in_(target_ids))
        .where(KnowledgeItem.status == "published")
    )
    if allowed_ids is not None:
        stmt = stmt.where(KnowledgeItem.id.in_(allowed_ids))
    if ctx is not None:
        stmt = scoped(stmt, ctx)
    if domain is not None:
        stmt = stmt.where(KnowledgeItem.domain == domain)
    if space_ids:
        stmt = stmt.where(KnowledgeItem.space_id.in_(space_ids))
    if tags:
        for tag in tags:
            stmt = stmt.where(
                KnowledgeItem.id.in_(
                    select(ItemTag.item_id).where(ItemTag.tag == tag.strip().lower())
                )
            )
    rows = session.execute(stmt).all()
    item_map: dict[uuid.UUID, tuple[KnowledgeItem, KnowledgeItemVersion]] = {
        item.id: (item, ver) for item, ver in rows
    }

    # Phase 3: build result _Scored, applying per-parent decay scores.
    extra: list[_Scored] = []
    for parent_score, edge_score, target_id, via_slug in candidates:
        pair = item_map.get(target_id)
        if pair is None:
            continue
        n_item, n_ver = pair
        extra.append(
            _Scored(
                score=edge_score * parent_score * settings.graph_expand_decay,
                item=n_item,
                version=n_ver,
                via_slug=via_slug,
                edge_score=edge_score,
                parent_score=parent_score,
                decay=settings.graph_expand_decay,
            )
        )
    return extra


# ---------------------------------------------------------------------------
# Hybrid implementation
# ---------------------------------------------------------------------------


class HybridSearchProvider:
    """Keyword + vector + recency blend with a relevance gate (Python rerank).

    Scoring:
        score = w_keyword * keyword_score
                + w_vector * max_chunk_cosine
                + w_recency * exp(-age_days / halflife_days)
                + w_importance * (degree / max_degree)

    By default ``search_w_recency`` and ``search_w_importance`` are 0.0, so
    scoring reduces to keyword + vector (the canonical hybrid blend); set the
    weights (config or env) to re-enable those signals.

    Relevance gate: an item is kept only if ``keyword_score > 0``
    OR ``max_chunk_cosine >= search_min_vector_similarity``.
    """

    def query(
        self,
        text: str,
        query_embedding: list[float],
        allowed_ids: set[uuid.UUID] | None,
        limit: int,
        session: Session,
        ctx: TenantContext | None = None,
        domain: str | None = None,
        tags: list[str] | None = None,
        space_ids: list[uuid.UUID] | None = None,
        explain: bool = False,
    ) -> list[SearchHit]:
        """Execute a hybrid search and return blended hits."""
        s = get_settings()
        now = datetime.now(timezone.utc)

        use_pgvector = session.get_bind().dialect.name == "postgresql"
        stmt = (
            select(KnowledgeItem, KnowledgeItemVersion)
            .join(
                KnowledgeItemVersion,
                KnowledgeItem.current_version_id == KnowledgeItemVersion.id,
            )
            .where(KnowledgeItem.status == "published")
            .where(KnowledgeItem.current_version_id.is_not(None))
        )
        # On Postgres the per-version cosine is computed in SQL
        # (_vector_similarity_map), so eager-loading chunk embeddings into Python
        # would be wasted I/O — only load them for the in-Python fallback path.
        if not use_pgvector:
            stmt = stmt.options(selectinload(KnowledgeItemVersion.chunks))
        if allowed_ids is not None:
            stmt = stmt.where(KnowledgeItem.id.in_(allowed_ids))
        if ctx is not None:
            stmt = scoped(stmt, ctx)
        if domain is not None:
            stmt = stmt.where(KnowledgeItem.domain == domain)
        if space_ids:
            stmt = stmt.where(KnowledgeItem.space_id.in_(space_ids))
        if tags:
            for tag in tags:
                stmt = stmt.where(
                    KnowledgeItem.id.in_(
                        select(ItemTag.item_id).where(ItemTag.tag == tag.strip().lower())
                    )
                )

        rows = session.execute(stmt).all()
        # Per-version best cosine: index-backed pgvector on Postgres, in-Python
        # otherwise. The map is built only over the already permission-filtered
        # versions, so it never scores restricted content.
        vmap = _vector_similarity_map(session, query_embedding, [v.id for _, v in rows])

        scored: list[_Scored] = []
        for item, version in rows:
            kw = _keyword_score(text, item.title, version.markdown_body)
            if vmap is not None:
                vec = vmap.get(version.id, 0.0)
            else:
                vec = max(
                    (cosine(query_embedding, c.embedding) for c in version.chunks),
                    default=0.0,
                )
            if kw == 0.0 and vec < s.search_min_vector_similarity:
                continue
            updated = item.updated_at
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            age_days = max((now - updated).total_seconds() / 86400.0, 0.0)
            rec = math.exp(-age_days / s.search_recency_halflife_days)
            score = s.search_w_keyword * kw + s.search_w_vector * vec + s.search_w_recency * rec
            scored.append(
                _Scored(score=score, item=item, version=version, kw=kw, vec=vec, rec=rec)
            )

        if s.search_w_importance and scored:
            degree = _degree_map(session, [sc.item.id for sc in scored])
            max_deg = max(degree.values(), default=0)
            if max_deg > 0:
                for sc in scored:
                    # Raw degree-centrality (0..1). The weight is applied to the
                    # score only, so the breakdown reports a 0..1 signal like the
                    # keyword/vector/recency components.
                    ratio = degree.get(sc.item.id, 0) / max_deg
                    sc.importance = ratio
                    sc.score += s.search_w_importance * ratio

        scored.sort(key=lambda sc: sc.score, reverse=True)
        if s.graph_expand_enabled and scored:
            scored.extend(
                _expand(
                    session,
                    scored,
                    {sc.item.id for sc in scored},
                    s,
                    allowed_ids,
                    ctx,
                    domain=domain,
                    tags=tags,
                    space_ids=space_ids,
                )
            )
            scored.sort(key=lambda sc: sc.score, reverse=True)
        return [
            SearchHit(
                id=sc.item.id,
                slug=sc.item.slug,
                title=sc.item.title,
                snippet=_make_snippet(sc.version.markdown_body),
                score=sc.score,
                breakdown=_build_breakdown(sc, s) if explain else None,
            )
            for sc in scored[:limit]
        ]


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


def get_search_provider() -> SearchProvider:
    """FastAPI dependency that returns the active ``SearchProvider``."""
    return HybridSearchProvider()
