"""Backfill chunk embeddings and vector graph edges for already-published pages.

Why this exists
---------------
``embed_activity`` and ``link_activity`` run at the *tail* of the ingest
workflow. Any page ingested while embedding was broken (or before embedding
existed) has zero ``wiki_chunks`` and therefore zero ``wiki_links`` — the
knowledge graph stays empty even though the pages are published.

This one-off (re-runnable, idempotent) script re-derives both for every
published page that has a current version:

  phase 1  embed every page   (so candidates exist for linking)
  phase 2  link every page     (top-K cosine neighbours among published pages)

Run it INSIDE the worker container so it inherits the gateway + DB settings::

    docker compose cp scripts/backfill_graph.py worker:/tmp/backfill_graph.py
    docker compose exec -T worker python /tmp/backfill_graph.py

It reuses the real activity functions, so behaviour matches live ingestion.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from k7e_api.db import SessionLocal
from k7e_api.models import KnowledgeItem
from k7e_worker.activities import embed_activity
from k7e_worker.link_activities import link_activity

# @activity.defn-decorated functions are directly callable, but unwrap to the
# plain coroutine via .fn when present to be safe outside a worker runtime.
_embed = getattr(embed_activity, "fn", embed_activity)
_link = getattr(link_activity, "fn", link_activity)


def _published_items() -> list[tuple[str, str]]:
    with SessionLocal() as session:
        rows = session.execute(
            select(KnowledgeItem.id, KnowledgeItem.current_version_id)
            .where(KnowledgeItem.status == "published")
            .where(KnowledgeItem.current_version_id.is_not(None))
        ).all()
    return [(str(item_id), str(version_id)) for item_id, version_id in rows]


async def main() -> None:
    items = _published_items()
    print(f"backfill: {len(items)} published page(s) with a current version")

    print("\n-- phase 1: embed --")
    embedded = 0
    for item_id, version_id in items:
        result = await _embed(version_id, item_id)
        chunks = result.get("chunk_count", 0)
        embedded += chunks
        print(f"  embed  {item_id[:8]}  chunks={chunks}")
    print(f"   total chunks written: {embedded}")

    print("\n-- phase 2: link --")
    total_edges = 0
    for item_id, _version_id in items:
        result = await _link(item_id)
        edges = result.get("edge_count", 0)
        total_edges += edges
        print(f"  link   {item_id[:8]}  neighbours={edges}")
    print(f"   total neighbour relations (per source): {total_edges}")
    print("\nbackfill complete.")


if __name__ == "__main__":
    asyncio.run(main())
