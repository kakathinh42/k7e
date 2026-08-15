"""Tests for GET /graph — the permission-aware knowledge-graph read."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from k7e_api.models import KnowledgeItem, KnowledgeItemVersion, WikiLink


def _now():
    return datetime.now(timezone.utc)


def _publish(session, slug: str, title: str) -> KnowledgeItem:
    """Create a published item with one current version. Returns the item."""
    item = KnowledgeItem(
        slug=slug, title=title, status="draft", created_at=_now(), updated_at=_now()
    )
    session.add(item)
    session.flush()
    version = KnowledgeItemVersion(
        item_id=item.id,
        version_number=1,
        markdown_body=f"# {title}\n\nbody",
        model_id="wiki-default",
        created_by="test",
        citations=[],
        status="published",
        title=title,
        created_at=_now(),
    )
    session.add(version)
    session.flush()
    item.current_version_id = version.id
    item.status = "published"
    return item


def _edge(session, src, tgt, score):
    """Add the symmetric vector edge pair the link-builder would write."""
    for a, b in ((src, tgt), (tgt, src)):
        session.add(
            WikiLink(
                source_item_id=a.id,
                target_item_id=b.id,
                relation="related",
                score=score,
                origin="vector",
            )
        )


def test_graph_returns_nodes_and_collapsed_edges(api_client, sqlite_factory):
    with sqlite_factory() as s:
        a = _publish(s, "page-a", "Page A")
        b = _publish(s, "page-b", "Page B")
        _publish(s, "page-c", "Page C")  # isolated node, no edges
        _edge(s, a, b, 0.83)
        s.commit()

    resp = api_client.get("/graph")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # 3 nodes; the symmetric A<->B pair collapses to ONE edge.
    assert len(body["nodes"]) == 3
    assert len(body["edges"]) == 1
    edge = body["edges"][0]
    assert {edge["source"], edge["target"]} == {
        str(a_id) for a_id in _ids(body, "page-a", "page-b")
    }
    assert edge["score"] == 0.83
    assert edge["relation"] == "related"

    # degree: A and B = 1, isolated C = 0
    deg = {n["slug"]: n["degree"] for n in body["nodes"]}
    assert deg == {"page-a": 1, "page-b": 1, "page-c": 0}


def test_graph_min_score_filters_weak_edges(api_client, sqlite_factory):
    with sqlite_factory() as s:
        a = _publish(s, "page-a", "Page A")
        b = _publish(s, "page-b", "Page B")
        _edge(s, a, b, 0.40)  # weak edge
        s.commit()

    # Above the floor -> edge dropped, nodes remain.
    resp = api_client.get("/graph", params={"min_score": 0.6})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["nodes"]) == 2
    assert body["edges"] == []
    assert all(n["degree"] == 0 for n in body["nodes"])


def _explicit_edge(session, src, tgt, score=1.0):
    """Add a directional explicit [[wikilink]] edge (src -> tgt)."""
    session.add(
        WikiLink(
            source_item_id=src.id,
            target_item_id=tgt.id,
            relation="related",
            score=score,
            origin="explicit",
        )
    )


def test_graph_reports_edge_origin_and_prefers_explicit(api_client, sqlite_factory):
    with sqlite_factory() as s:
        a = _publish(s, "page-a", "Page A")
        b = _publish(s, "page-b", "Page B")
        c = _publish(s, "page-c", "Page C")
        _edge(s, a, b, 0.70)  # vector pair A<->B
        _explicit_edge(s, a, b, 1.0)  # same pair ALSO explicit -> should win
        _explicit_edge(s, a, c, 1.0)  # explicit-only pair A->C
        s.commit()

    body = api_client.get("/graph").json()
    edges = {frozenset((e["source"], e["target"])): e for e in body["edges"]}
    assert len(edges) == 2

    ids = {n["slug"]: n["id"] for n in body["nodes"]}
    ab = edges[frozenset((ids["page-a"], ids["page-b"]))]
    ac = edges[frozenset((ids["page-a"], ids["page-c"]))]
    assert ab["origin"] == "explicit"  # explicit beats vector for the same pair
    assert ab["score"] == 1.0
    assert ac["origin"] == "explicit"


def test_graph_excludes_unpublished_nodes(api_client, sqlite_factory):
    with sqlite_factory() as s:
        _publish(s, "live", "Live")
        # a draft item (never published) must not appear as a node
        draft = KnowledgeItem(
            slug="draftish",
            title="Draft",
            status="draft",
            created_at=_now(),
            updated_at=_now(),
        )
        s.add(draft)
        s.commit()

    body = api_client.get("/graph").json()
    slugs = {n["slug"] for n in body["nodes"]}
    assert slugs == {"live"}


def _ids(body, *slugs) -> list[uuid.UUID]:
    by_slug = {n["slug"]: uuid.UUID(n["id"]) for n in body["nodes"]}
    return [by_slug[s] for s in slugs]


def test_graph_excludes_edge_from_out_of_scope_source(api_client, sqlite_factory):
    """A WikiLink whose source is not in the visible set must not appear as an edge.

    Regression guard for the /graph source-filter fix: before the fix this row was
    loaded and discarded in Python; after the fix it is not loaded from the DB.
    The observable result is identical either way — this test documents the
    required behaviour.
    """
    with sqlite_factory() as s:
        a = _publish(s, "alpha", "Alpha")
        # Draft item — no current_version_id, status="draft" → not in node_ids.
        d = KnowledgeItem(
            slug="draft-page",
            title="Draft",
            status="draft",
            created_at=_now(),
            updated_at=_now(),
        )
        s.add(d)
        s.flush()
        # Stray edge: source is the draft (out of scope), target is published.
        s.add(
            WikiLink(
                source_item_id=d.id,
                target_item_id=a.id,
                relation="related",
                score=0.9,
                origin="vector",
            )
        )
        s.commit()

    body = api_client.get("/graph").json()
    # Only the published item is a node; draft is excluded.
    assert len(body["nodes"]) == 1
    assert body["nodes"][0]["slug"] == "alpha"
    # The stray edge from draft→alpha must NOT appear.
    assert body["edges"] == []
    assert body["nodes"][0]["degree"] == 0
