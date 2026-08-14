"""KnowledgeItem.provenance column: nullable JSON, defaults to None."""

from __future__ import annotations

from k7e_api.models import KnowledgeItem


def test_provenance_defaults_to_none(sqlite_factory):
    """A KnowledgeItem created without provenance is None after flush."""
    with sqlite_factory() as s:
        item = KnowledgeItem(slug="p1", title="P1", status="draft", type="source")
        s.add(item)
        s.flush()
        assert item.provenance is None


def test_provenance_round_trips_a_dict(sqlite_factory):
    """A provenance dict is stored and read back intact."""
    payload = {"resource": "abc", "source_pages": ["a", "b"]}
    with sqlite_factory() as s:
        item = KnowledgeItem(
            slug="p2",
            title="P2",
            status="published",
            type="concept",
            provenance=payload,
        )
        s.add(item)
        s.flush()
        s.expire(item)
        assert item.provenance == payload
