"""Deterministic source identity: map (source_system, source_external_id) to a page.

This is the Tier-A dedup primitive — re-ingesting the same external source
resolves to the SAME KnowledgeItem, so a new ingest becomes an update of that
page rather than a fork.
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from k7e_api.models import KnowledgeItem, SourcePageLink


def resolve_linked_item(
    session: Session, source_system: str, source_external_id: Optional[str]
) -> Optional[KnowledgeItem]:
    """Return the KnowledgeItem linked to this source, or None.

    A null/empty external id is never linkable (ad-hoc sources have no stable id).
    """
    if not source_external_id:
        return None
    link = session.execute(
        select(SourcePageLink).where(
            SourcePageLink.source_system == source_system,
            SourcePageLink.source_external_id == source_external_id,
        )
    ).scalar_one_or_none()
    if link is None:
        return None
    return session.get(KnowledgeItem, link.knowledge_item_id)


def record_source_link(
    session: Session,
    source_system: str,
    source_external_id: Optional[str],
    knowledge_item_id: uuid.UUID,
) -> None:
    """Idempotently record a source -> page link.

    No-op for a null external id or when the link already exists.
    """
    if not source_external_id:
        return
    existing = session.execute(
        select(SourcePageLink).where(
            SourcePageLink.source_system == source_system,
            SourcePageLink.source_external_id == source_external_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return
    # Phase 5 TODO: org_id left NULL here (legacy v1 path, not on live pipeline); backfilled by migration 0016
    session.add(
        SourcePageLink(
            source_system=source_system,
            source_external_id=source_external_id,
            knowledge_item_id=knowledge_item_id,
        )
    )
