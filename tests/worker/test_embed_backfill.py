"""embed_backfill_activity embeds a bounded batch, is resumable, and fail-fast."""

from __future__ import annotations

import k7e_worker.embed_backfill as bf
from k7e_api.models import KnowledgeItem, KnowledgeItemVersion, WikiChunk
from sqlalchemy import func, select


class _StubEmbed:
    async def embed(self, texts):
        return [[float(len(t))] * 4 for t in texts]


class _BoomEmbed:
    async def embed(self, texts):
        raise RuntimeError("429")


def _seed_null_chunks(session_factory, n):
    with session_factory() as s:
        item = KnowledgeItem(slug="p", type="concept", title="P", status="published")
        s.add(item)
        s.flush()
        ver = KnowledgeItemVersion(
            item_id=item.id,
            version_number=1,
            markdown_body="b",
            model_id="m",
            created_by="t",
            status="published",
            title="P",
            citations=[],
        )
        s.add(ver)
        s.flush()
        for i in range(n):
            s.add(
                WikiChunk(
                    item_id=item.id,
                    version_id=ver.id,
                    chunk_index=i,
                    chunk_text=f"chunk {i}",
                    embedding=None,
                )
            )
        s.commit()


def _null_count(session_factory):
    with session_factory() as s:
        return s.execute(
            select(func.count()).select_from(WikiChunk).where(WikiChunk.embedding.is_(None))
        ).scalar_one()


async def test_backfill_embeds_one_bounded_batch_and_is_resumable(sqlite_factory, monkeypatch):
    _seed_null_chunks(sqlite_factory, 5)
    monkeypatch.setattr(bf, "session_factory", sqlite_factory)
    monkeypatch.setattr(bf, "embedding_client_factory", lambda: _StubEmbed())
    monkeypatch.setattr(bf, "get_settings", lambda: bf._Cfg(batch=2, enabled=True))

    r1 = await bf.embed_backfill_activity()
    assert r1["embedded"] == 2 and r1["remaining"] == 3
    r2 = await bf.embed_backfill_activity()
    assert r2["embedded"] == 2 and r2["remaining"] == 1
    r3 = await bf.embed_backfill_activity()
    assert r3["embedded"] == 1 and r3["remaining"] == 0
    assert _null_count(sqlite_factory) == 0


async def test_backfill_failfast_leaves_null_and_does_not_raise(sqlite_factory, monkeypatch):
    _seed_null_chunks(sqlite_factory, 3)
    monkeypatch.setattr(bf, "session_factory", sqlite_factory)
    monkeypatch.setattr(bf, "embedding_client_factory", lambda: _BoomEmbed())
    monkeypatch.setattr(bf, "get_settings", lambda: bf._Cfg(batch=2, enabled=True))
    r = await bf.embed_backfill_activity()  # must not raise
    assert r["embedded"] == 0
    assert _null_count(sqlite_factory) == 3


async def test_backfill_noop_when_disabled(sqlite_factory, monkeypatch):
    _seed_null_chunks(sqlite_factory, 2)
    monkeypatch.setattr(bf, "session_factory", sqlite_factory)
    monkeypatch.setattr(bf, "embedding_client_factory", lambda: _BoomEmbed())
    monkeypatch.setattr(bf, "get_settings", lambda: bf._Cfg(batch=2, enabled=False))
    r = await bf.embed_backfill_activity()
    assert r["embedded"] == 0 and _null_count(sqlite_factory) == 2
