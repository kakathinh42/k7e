"""WikiChunk.embedding is nullable so chunks can be persisted text-first."""

from __future__ import annotations

from k7e_api.models import KnowledgeItem, KnowledgeItemVersion, WikiChunk
from sqlalchemy import select


def test_embedding_column_is_nullable():
    """The mapped ``embedding`` column must allow NULL (backfill-later).

    Asserted at the ORM-metadata level because the SQLite test dialect stores
    the JSON-backed column's Python ``None`` as the JSON literal ``'null'``
    (non-NULL), so a NOT NULL column would not raise on the ORM insert path —
    only the real Postgres pgvector column enforces NOT NULL at insert time.
    """
    assert WikiChunk.__table__.c.embedding.nullable is True


def test_chunk_persists_with_null_embedding(sqlite_factory):
    with sqlite_factory() as s:
        item = KnowledgeItem(slug="x", type="concept", title="X", status="published")
        s.add(item)
        s.flush()
        ver = KnowledgeItemVersion(
            item_id=item.id,
            version_number=1,
            markdown_body="body",
            model_id="m",
            created_by="t",
            status="published",
            title="X",
            citations=[],
        )
        s.add(ver)
        s.flush()
        s.add(
            WikiChunk(
                item_id=item.id,
                version_id=ver.id,
                chunk_index=0,
                chunk_text="hello",
                embedding=None,
            )
        )
        s.commit()
        row = s.execute(select(WikiChunk)).scalars().one()
        assert row.chunk_text == "hello"
        assert row.embedding is None
