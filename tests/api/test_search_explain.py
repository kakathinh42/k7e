"""Explain mode: query(explain=True) returns a self-consistent per-hit breakdown."""

from __future__ import annotations

from k7e_api.models import KnowledgeItem, KnowledgeItemVersion
from k7e_api.search import HybridSearchProvider


def _seed_item(s, *, slug, title, body):
    item = KnowledgeItem(slug=slug, type="concept", title=title, status="published")
    s.add(item)
    s.flush()
    ver = KnowledgeItemVersion(
        item_id=item.id,
        version_number=1,
        markdown_body=body,
        model_id="m",
        created_by="t",
        status="published",
        title=title,
        citations=[],
    )
    s.add(ver)
    s.flush()
    item.current_version_id = ver.id
    s.flush()
    return item, ver


def test_direct_hit_breakdown_reproduces_score(sqlite_factory):
    with sqlite_factory() as s:
        _seed_item(
            s,
            slug="points",
            title="Points expiry",
            body="Loyalty points expire after 12 months of inactivity.",
        )
        s.commit()
        hits = HybridSearchProvider().query(
            text="points expire",
            query_embedding=[],
            allowed_ids=None,
            limit=10,
            session=s,
            explain=True,
        )
        assert hits, "expected a keyword hit"
        h = hits[0]
        b = h.breakdown
        assert b is not None
        assert b.expanded is False
        # Blend is self-consistent: Σ weightᵢ·componentᵢ == total (== score).
        recomputed = (
            b.weights["keyword"] * b.keyword
            + b.weights["vector"] * b.vector
            + b.weights["recency"] * b.recency
            + b.weights["importance"] * b.importance
        )
        assert abs(recomputed - b.total) < 1e-6
        assert abs(b.total - h.score) < 1e-6


def test_default_config_scores_only_keyword_and_vector(sqlite_factory):
    """Under default settings, only keyword + vector contribute to the score."""
    with sqlite_factory() as s:
        _seed_item(
            s,
            slug="points",
            title="Points expiry",
            body="Loyalty points expire after 12 months of inactivity.",
        )
        s.commit()
        hits = HybridSearchProvider().query(
            text="points expire",
            query_embedding=[],
            allowed_ids=None,
            limit=10,
            session=s,
            explain=True,
        )
        assert hits
        b = hits[0].breakdown
        assert b is not None
        # recency + importance are disabled by default.
        assert b.weights["recency"] == 0.0
        assert b.weights["importance"] == 0.0
        # The score is exactly the keyword + vector contribution.
        expected = b.weights["keyword"] * b.keyword + b.weights["vector"] * b.vector
        assert abs(hits[0].score - expected) < 1e-6


def test_explain_false_leaves_breakdown_none(sqlite_factory):
    with sqlite_factory() as s:
        _seed_item(s, slug="points", title="Points", body="points expire in 12 months")
        s.commit()
        hits = HybridSearchProvider().query(
            text="points",
            query_embedding=[],
            allowed_ids=None,
            limit=10,
            session=s,  # explain defaults False
        )
        assert hits and hits[0].breakdown is None
