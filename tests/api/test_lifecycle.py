"""Tests for soft-archive (retire) — DELETE /items/{slug} + lifecycle.archive_item."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from k7e_api.models import (
    KnowledgeItem,
    KnowledgeItemVersion,
    SourcePageLink,
    WikiLink,
)


def _now():
    return datetime.now(timezone.utc)


def _publish(session, slug: str, title: str) -> KnowledgeItem:
    item = KnowledgeItem(
        slug=slug, title=title, status="draft", created_at=_now(), updated_at=_now()
    )
    session.add(item)
    session.flush()
    version = KnowledgeItemVersion(
        item_id=item.id,
        version_number=1,
        markdown_body=f"# {title}",
        model_id="m",
        created_by="t",
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


def test_archive_hides_item_and_detaches_edges(api_client, sqlite_factory):
    with sqlite_factory() as s:
        a = _publish(s, "page-a", "Page A")
        b = _publish(s, "page-b", "Page B")
        # symmetric vector edge A<->B and a source link for A
        s.add_all(
            [
                WikiLink(
                    source_item_id=a.id,
                    target_item_id=b.id,
                    relation="related",
                    score=0.8,
                    origin="vector",
                ),
                WikiLink(
                    source_item_id=b.id,
                    target_item_id=a.id,
                    relation="related",
                    score=0.8,
                    origin="vector",
                ),
                SourcePageLink(
                    source_system="manual_upload",
                    source_external_id="sha-a",
                    knowledge_item_id=a.id,
                ),
            ]
        )
        s.commit()
        a_id = a.id

    # Archive A
    resp = api_client.delete("/items/page-a")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "archived"

    # A is gone from listing + detail + (any) graph
    listed = {i["slug"] for i in api_client.get("/items").json()}
    assert listed == {"page-b"}
    assert api_client.get("/items/page-a").status_code == 404

    # Edges touching A and A's source link are removed; B survives intact.
    with sqlite_factory() as s:
        links = s.query(WikiLink).all()
        assert all(a_id not in (link.source_item_id, link.target_item_id) for link in links)
        assert s.query(SourcePageLink).count() == 0
        assert s.get(KnowledgeItem, a_id).status == "archived"


def test_archive_unknown_slug_404(api_client):
    assert api_client.delete("/items/does-not-exist").status_code == 404


def test_archive_twice_is_404_second_time(api_client, sqlite_factory):
    with sqlite_factory() as s:
        _publish(s, "solo", "Solo")
        s.commit()
    assert api_client.delete("/items/solo").status_code == 200
    # already archived -> no longer "published" -> not found
    assert api_client.delete("/items/solo").status_code == 404


def test_re_ingest_after_archive_does_not_resolve_to_retired_page(api_client, sqlite_factory):
    """Removing the source link means a later re-ingest starts fresh."""
    from k7e_api.identity import resolve_linked_item

    with sqlite_factory() as s:
        item = _publish(s, "doc", "Doc")
        s.add(
            SourcePageLink(
                source_system="confluence",
                source_external_id="PAGE-1",
                knowledge_item_id=item.id,
            )
        )
        s.commit()

    api_client.delete("/items/doc")

    with sqlite_factory() as s:
        assert resolve_linked_item(s, "confluence", "PAGE-1") is None


def test_archive_item_helper_is_idempotent_on_edges(sqlite_factory):
    """Direct unit test of the service helper."""
    from k7e_api.lifecycle import archive_item

    with sqlite_factory() as s:
        a = _publish(s, "x", "X")
        s.commit()
        archive_item(s, a)
        s.commit()
        assert a.status == "archived"
        assert s.query(WikiLink).count() == 0
        assert uuid.UUID(str(a.id))  # id still valid; row retained
