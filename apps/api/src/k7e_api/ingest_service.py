"""Idempotent ingest service used by connectors (and reusable by the API).

Stores a FetchedDocument and starts the ingest workflow, unless the same source
identity already has a RawDocument with an identical content hash — in which case
the document is unchanged and we skip it. Changed content is ingested and flows
through the pipeline as a reviewed update (Phase 1-2).
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import uuid
from typing import Awaitable, Callable, Union

from sqlalchemy import select
from sqlalchemy.orm import Session

from k7e_api.connectors.base import Connector, FetchedDocument
from k7e_api.models import RawDocument

WorkflowStarter = Callable[[str], Union[str, Awaitable[str]]]


def as_sync_workflow_starter(starter: WorkflowStarter) -> Callable[[str], str]:
    """Adapt a possibly-async workflow starter to a sync callable.

    Sync callers (the connector + /ingest/source routes run in a threadpool
    worker with no running loop) run an async production ``start_ingest_workflow``
    to completion via ``asyncio.run``; a sync test fake passes through unchanged.
    """

    def _run(raw_id: str):
        result = starter(raw_id)
        if inspect.isawaitable(result):
            return asyncio.run(result)
        return result

    return _run


def _latest_raw(
    session: Session, source_system: str, source_external_id: str, org_id
) -> RawDocument | None:
    """The most recent RawDocument for this source identity *within one org*.

    Org-scoped so an idempotent skip can never match — or return the id of — a
    document belonging to a different tenant. ``org_id is None`` matches the
    unscoped/global rows written by callers that don't set a tenant.
    """
    return (
        session.execute(
            select(RawDocument)
            .where(
                RawDocument.source_system == source_system,
                RawDocument.source_external_id == source_external_id,
                RawDocument.org_id == org_id,
            )
            .order_by(RawDocument.created_at.desc())
        )
        .scalars()
        .first()
    )


def ingest_document(
    session: Session,
    object_store,
    workflow_starter: WorkflowStarter,
    doc: FetchedDocument,
    *,
    org_id=None,
    allowed_groups=None,
    space_id: uuid.UUID | None = None,
    created_by: str | None = None,
) -> dict:
    """Store + ingest one FetchedDocument idempotently."""
    sha256 = hashlib.sha256(doc.content).hexdigest()
    latest = _latest_raw(session, doc.source_system, doc.source_external_id, org_id)
    if latest is not None and latest.sha256 == sha256:
        return {
            "status": "skipped",
            "reason": "unchanged",
            "raw_document_id": str(latest.id),
            "workflow_id": latest.workflow_id,
        }

    object_key = f"raw/{doc.source_system}/{sha256}.bin"
    ref = object_store.put(object_key, doc.content)

    raw = RawDocument(
        filename=doc.filename,
        sha256=sha256,
        object_store_ref=ref,
        mime_type=doc.content_type,
        size_bytes=len(doc.content),
        status="received",
        source_system=doc.source_system,
        source_external_id=doc.source_external_id,
        source_tier=doc.source_tier,
        org_id=org_id,
        allowed_groups=allowed_groups,
        space_id=space_id,
        created_by=created_by,
        extra_metadata=doc.extra_metadata,
    )
    session.add(raw)
    session.flush()
    session.commit()

    workflow_id = workflow_starter(str(raw.id))
    if inspect.isawaitable(workflow_id):  # pragma: no cover - callers pass sync-adapted starters
        raise RuntimeError(
            "ingest_document requires a synchronous workflow_starter; wrap async "
            "starters with as_sync_workflow_starter()"
        )
    raw.workflow_id = workflow_id
    session.commit()

    return {
        "status": "ingested",
        "raw_document_id": str(raw.id),
        "workflow_id": workflow_id,
    }


def run_connector(
    session: Session,
    object_store,
    workflow_starter: WorkflowStarter,
    connector: Connector,
    *,
    org_id=None,
    allowed_groups=None,
) -> dict:
    """Run a connector and ingest every document it yields. Returns counts."""
    ingested = skipped = 0
    for doc in connector.fetch():
        res = ingest_document(
            session,
            object_store,
            workflow_starter,
            doc,
            org_id=org_id,
            allowed_groups=allowed_groups,
        )
        if res["status"] == "ingested":
            ingested += 1
        else:
            skipped += 1
    return {"connector": connector.name, "ingested": ingested, "skipped": skipped}
