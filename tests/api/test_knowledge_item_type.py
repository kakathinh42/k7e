"""KnowledgeItem.type column: defaults to 'source' on insert."""

from __future__ import annotations

from k7e_api.models import KnowledgeItem


def test_knowledge_item_defaults_type_to_source(sqlite_factory):
    """A KnowledgeItem created without an explicit type is 'source' after flush."""
    with sqlite_factory() as s:
        item = KnowledgeItem(slug="defaults-page", title="Defaults", status="draft")
        s.add(item)
        s.flush()
        assert item.type == "source"


def test_knowledge_item_accepts_explicit_type(sqlite_factory):
    """An explicit type is persisted verbatim."""
    with sqlite_factory() as s:
        item = KnowledgeItem(
            slug="concept-page", title="Concept", status="published", type="concept"
        )
        s.add(item)
        s.flush()
        assert item.type == "concept"
