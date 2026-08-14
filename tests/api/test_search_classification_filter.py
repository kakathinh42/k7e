"""M4: search narrows by domain/tag before ranking."""

from __future__ import annotations

from k7e_api.models import ItemTag, KnowledgeItem, KnowledgeItemVersion
from k7e_api.search import HybridSearchProvider


def _publish(session, slug, *, domain, tags=()):
    item = KnowledgeItem(slug=slug, title=slug, status="published", domain=domain)
    session.add(item)
    session.flush()
    ver = KnowledgeItemVersion(
        item_id=item.id,
        version_number=1,
        markdown_body=f"# {slug}\n\nretry policy content",
        model_id="t",
        created_by="t",
        citations=[],
        status="published",
        title=slug,
    )
    session.add(ver)
    session.flush()
    item.current_version_id = ver.id
    for tag in tags:
        session.add(ItemTag(item_id=item.id, tag=tag))


def test_search_filters_by_domain(sqlite_factory):
    with sqlite_factory() as s:
        _publish(s, "be", domain="backend", tags=["retry"])
        _publish(s, "fe", domain="frontend", tags=["retry"])
        s.commit()
    with sqlite_factory() as s:
        hits = HybridSearchProvider().query(
            text="retry",
            query_embedding=[],
            allowed_ids=None,
            limit=20,
            session=s,
            domain="backend",
        )
        assert {h.slug for h in hits} == {"be"}


def test_search_filters_by_tag(sqlite_factory):
    with sqlite_factory() as s:
        _publish(s, "a", domain="backend", tags=["redis"])
        _publish(s, "b", domain="backend", tags=["kafka"])
        s.commit()
    with sqlite_factory() as s:
        hits = HybridSearchProvider().query(
            text="retry",
            query_embedding=[],
            allowed_ids=None,
            limit=20,
            session=s,
            tags=["redis"],
        )
        assert {h.slug for h in hits} == {"a"}
