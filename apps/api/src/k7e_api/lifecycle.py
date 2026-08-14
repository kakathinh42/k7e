"""Page lifecycle transitions beyond ingest — currently soft-archive (retire).

Removal in this system is intentionally *soft*: knowledge_items rows are never
deleted (provenance + audit), they transition to ``status="archived"``. Because
every read path (search, graph expansion, item listing/detail) filters to
``status == "published"``, an archived page simply disappears from retrieval.

Archiving also detaches the page from the graph and identity maps so it leaves
no dangling references:

* ``wiki_links`` touching the page (either direction) are removed — neighbours
  stop expanding into it and its out-degree no longer inflates importance.
* its ``source_page_links`` are removed — a later re-ingest of the same source
  starts a fresh page instead of resolving to the retired one.

Versions and chunks are deliberately retained.
"""

from __future__ import annotations

from sqlalchemy import delete, or_
from sqlalchemy.orm import Session

from k7e_api.models import KnowledgeItem, SourcePageLink, WikiLink


def archive_item(session: Session, item: KnowledgeItem) -> None:
    """Soft-archive ``item`` and detach its graph + identity edges.

    The caller is responsible for committing the session.
    """
    item.status = "archived"
    session.execute(
        delete(WikiLink).where(
            or_(
                WikiLink.source_item_id == item.id,
                WikiLink.target_item_id == item.id,
            )
        )
    )
    session.execute(delete(SourcePageLink).where(SourcePageLink.knowledge_item_id == item.id))
