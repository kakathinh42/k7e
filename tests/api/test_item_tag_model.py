"""M4: KnowledgeItem.domain column + ItemTag join table."""

from __future__ import annotations

from k7e_api.models import ItemTag, KnowledgeItem


def test_item_has_domain_and_tags(sqlite_factory):
    with sqlite_factory() as s:
        item = KnowledgeItem(slug="p", title="P", status="published", domain="backend")
        s.add(item)
        s.flush()
        s.add(ItemTag(item_id=item.id, tag="redis"))
        s.add(ItemTag(item_id=item.id, tag="cache"))
        s.commit()

    with sqlite_factory() as s:
        got = s.query(KnowledgeItem).filter_by(slug="p").one()
        assert got.domain == "backend"
        tags = {t.tag for t in s.query(ItemTag).filter_by(item_id=got.id)}
        assert tags == {"redis", "cache"}


def test_item_tag_unique_per_item_tag(sqlite_factory):
    import pytest
    from sqlalchemy.exc import IntegrityError

    with sqlite_factory() as s:
        item = KnowledgeItem(slug="p", title="P", status="published")
        s.add(item)
        s.flush()
        s.add(ItemTag(item_id=item.id, tag="redis"))
        s.add(ItemTag(item_id=item.id, tag="redis"))
        with pytest.raises(IntegrityError):
            s.commit()
