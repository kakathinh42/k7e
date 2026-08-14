"""allowed_groups columns: nullable JSON on KnowledgeItem and RawDocument."""

from __future__ import annotations

from k7e_api.models import KnowledgeItem, RawDocument


def test_knowledge_item_allowed_groups_defaults_none(sqlite_factory):
    with sqlite_factory() as s:
        item = KnowledgeItem(slug="g1", title="G1", status="draft", type="source")
        s.add(item)
        s.flush()
        assert item.allowed_groups is None


def test_knowledge_item_allowed_groups_round_trips(sqlite_factory):
    with sqlite_factory() as s:
        item = KnowledgeItem(
            slug="g2",
            title="G2",
            status="published",
            type="source",
            allowed_groups=["finance", "exec"],
        )
        s.add(item)
        s.flush()
        s.expire(item)
        assert item.allowed_groups == ["finance", "exec"]


def test_raw_document_allowed_groups_round_trips(sqlite_factory):
    with sqlite_factory() as s:
        raw = RawDocument(
            filename="f.md",
            sha256="a" * 64,
            object_store_ref="raw/x",
            mime_type="text/markdown",
            allowed_groups=["eng"],
        )
        s.add(raw)
        s.flush()
        s.expire(raw)
        assert raw.allowed_groups == ["eng"]
