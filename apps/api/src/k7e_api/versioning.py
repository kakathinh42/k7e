"""Markdown versioning service.

Provides :func:`upsert_item_version` which:

1. Finds or creates a :class:`~k7e_api.models.KnowledgeItem` by slug.
2. Determines the next sequential version number for that item.
3. Inserts a new :class:`~k7e_api.models.KnowledgeItemVersion` with the
   interpreted Markdown body, citations, and provenance metadata.
4. If the gate decision is ``"publish"``, promotes the new version to be the
   item's current (live) version and marks the item as ``"published"``.

Design notes
------------
* ``updated_at`` on :class:`~k7e_api.models.KnowledgeItem` is declared with
  ``onupdate=_utcnow``, but that hook only fires on UPDATE statements issued
  through the ORM's unit-of-work flush when a mapped attribute changes.  To
  make it reliable we also set the column explicitly via ``item.updated_at``.
* The circular foreign key
  ``knowledge_items.current_version_id -> knowledge_item_versions.id``
  uses ``post_update=True`` on the SQLAlchemy relationship so that the version
  row is inserted first and the back-pointer update is deferred to a second
  flush.  We call ``session.flush()`` once after creating the version so the
  version's ``id`` is populated, and again (implicitly via commit/flush) after
  setting ``current_version_id``.
* ``extra_metadata`` on :class:`~k7e_api.models.KnowledgeItemVersion` is
  optional / nullable in the schema.  We leave it as ``None`` (no extra data
  beyond what the task specifies).
* ``raw_document_id`` on the version is nullable in the schema; we store the
  caller-supplied value directly (which may legitimately be ``None``, though
  normal usage always passes a real UUID from the ingestion pipeline).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from k7e_api.gate import GateOutcome
from k7e_api.interpretation import Interpretation
from k7e_api.models import KnowledgeItem, KnowledgeItemVersion


def _utcnow() -> datetime:
    """Return the current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


def upsert_item_version(
    session: Session,
    *,
    interp: Interpretation,
    raw_document_id: Optional[uuid.UUID],
    model_id: str,
    gate: GateOutcome,
    created_by: str,
    target_item: Optional[KnowledgeItem] = None,
) -> KnowledgeItemVersion:
    """Create or update a :class:`~k7e_api.models.KnowledgeItem` and append a new version.

    Args:
        session: An open SQLAlchemy :class:`~sqlalchemy.orm.Session`.
        interp: The :class:`~k7e_api.interpretation.Interpretation` produced by
            the LLM pipeline.
        raw_document_id: UUID of the originating
            :class:`~k7e_api.models.RawDocument`.  May be ``None`` in tests
            that do not seed the ``raw_documents`` table.
        model_id: Identifier of the LLM model that produced the interpretation
            (e.g. ``"gpt-4o"`` or ``"wiki-default"``).
        gate: The :class:`~k7e_api.gate.GateOutcome` from the gate policy
            evaluation.  When ``gate.decision == "publish"`` the item is
            promoted to published status and its ``current_version_id`` is
            updated.
        created_by: Identifier (e.g. user-id or service name) of the actor
            triggering the ingestion.

    Returns:
        The newly inserted :class:`~k7e_api.models.KnowledgeItemVersion`.

    Column choices for required-but-unspecified fields
    ---------------------------------------------------
    * ``KnowledgeItemVersion.extra_metadata`` – set to ``None`` (nullable,
      no additional metadata beyond the fields in the task spec).
    """
    now = _utcnow()

    # ------------------------------------------------------------------
    # 1. Resolve the target KnowledgeItem: an explicit target (from source
    #    identity) wins; otherwise find-or-create by slug.
    # ------------------------------------------------------------------
    if target_item is not None:
        item: Optional[KnowledgeItem] = target_item
    else:
        item = session.execute(
            select(KnowledgeItem).where(KnowledgeItem.slug == interp.slug)
        ).scalar_one_or_none()

    if item is None:
        # Phase 5 TODO: org_id left NULL here (legacy v1 path, not on live pipeline); backfilled by migration 0016
        item = KnowledgeItem(
            slug=interp.slug,
            title=interp.title,
            status="draft",
            created_at=now,
            updated_at=now,
        )
        session.add(item)
        session.flush()  # populate item.id before referencing it below

    # Whether this page already has a live, published version. When it does, the
    # live item (title/updated_at/current_version_id) must NOT change until a
    # human approves the new version (handled in the review router).
    is_live = item.current_version_id is not None

    # ------------------------------------------------------------------
    # 2. Determine the next version number
    # ------------------------------------------------------------------
    max_version_number: Optional[int] = session.execute(
        select(func.max(KnowledgeItemVersion.version_number)).where(
            KnowledgeItemVersion.item_id == item.id
        )
    ).scalar_one_or_none()

    next_version_number: int = (max_version_number or 0) + 1

    # ------------------------------------------------------------------
    # 3. Insert the new KnowledgeItemVersion, carrying its own lifecycle
    #    status and a title snapshot.
    # ------------------------------------------------------------------
    version_status = {
        "publish": "published",
        "review": "pending_review",
        "reject": "rejected",
    }.get(gate.decision, "pending_review")

    citations_json = [c.model_dump(mode="json") for c in interp.citations]

    new_version = KnowledgeItemVersion(
        item_id=item.id,
        raw_document_id=raw_document_id,
        version_number=next_version_number,
        markdown_body=interp.markdown_body,
        model_id=model_id,
        created_by=created_by,
        citations=citations_json,
        extra_metadata=None,  # no additional metadata in MVP
        status=version_status,
        title=interp.title,
        created_at=now,
    )
    session.add(new_version)
    session.flush()  # populate new_version.id before we might set current_version_id

    # ------------------------------------------------------------------
    # 4. Mutate the live item ONLY when this version is being published now.
    #    For a non-live draft we still track its title (there is no live page to
    #    protect); for a published page we leave title/updated_at/
    #    current_version_id alone until a human approves.
    # ------------------------------------------------------------------
    if gate.decision == "publish":
        item.current_version_id = new_version.id
        item.status = "published"
        item.title = interp.title
        item.updated_at = now
        session.flush()  # apply the post_update relationship back-pointer
    elif not is_live:
        # Draft item that was never published: keep its title current.
        item.title = interp.title
        item.updated_at = now

    return new_version
