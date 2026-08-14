"""Temporal activity definitions shared by the k7e ingestion pipeline.

Activities:
- ``load_raw_document``: Load raw document bytes and metadata from the object store.
- ``redact_activity``: Apply deterministic PII redaction to document text.

These are the two deterministic front-of-pipeline activities. The v2 OKF ingest
(extract → resolve → compose → commit → mirror) lives in
``k7e_worker.okf_activities``.

Design notes
------------
* ``session_factory`` is a module-level variable (default: ``k7e_api.db.SessionLocal``)
  that can be overridden in tests with an in-memory SQLite sessionmaker to avoid
  requiring a running PostgreSQL instance.

* ``load_raw_document`` reads the file bytes directly from the path stored in
  ``raw_document.object_store_ref`` using ``pathlib.Path.read_bytes()``.
  ``LocalFileObjectStore.put()`` returns an absolute path, so ``object_store_ref``
  is an absolute filesystem path; reading via ``Path(ref).read_bytes()`` avoids any
  base-directory mismatch.

* Activities decorated with ``@activity.defn`` can be called directly outside
  a Temporal worker context (the SDK allows this). If needed, the underlying
  coroutine function is accessible via the ``.fn`` attribute.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from k7e_api.db import SessionLocal
from k7e_api.logging_setup import get_logger
from k7e_api.redaction import redact
from k7e_api.validation import EXTRACTABLE_MIME
from temporalio import activity
from temporalio.exceptions import ApplicationError

# ---------------------------------------------------------------------------
# Module-level overridable factories
# ---------------------------------------------------------------------------

#: Session factory used to open SQLAlchemy sessions.
#: Override in tests with a SQLite-backed sessionmaker to avoid PostgreSQL.
session_factory = SessionLocal

#: Module-level structlog logger. Reuses the API's JSON logging contract so
#: worker and API logs share an identical format.
logger = get_logger(__name__)


def _activity_log_context(
    event: str,
    activity_name: str,
    raw_document_id: str | None = None,
) -> dict:
    """Build the base structured-log context dict for an activity event.

    This is the single seam in the worker that touches
    ``temporalio.activity.info()``. ``activity.info()`` raises ``RuntimeError``
    when called outside a Temporal worker (e.g. in direct-call unit tests),
    so we wrap it in a broad ``try``/``except`` and silently omit the Temporal
    correlation fields on failure — logging must never raise.

    Args:
        event: structlog event key, e.g. ``"activity_started"`` /
            ``"activity_completed"``. Used as the log message key.
        activity_name: Static activity name (e.g. ``"redact_activity"``).
        raw_document_id: Included as a correlation field when the activity
            receives one as a parameter; omitted otherwise.

    Returns:
        Dict suitable for unpacking into ``logger.info(**ctx, ...)``.
    """
    ctx: dict = {"event": event, "activity": activity_name}
    try:
        info = activity.info()
        ctx["workflow_id"] = info.workflow_id
        ctx["workflow_run_id"] = info.workflow_run_id
        ctx["activity_id"] = info.activity_id
        ctx["attempt"] = info.attempt
    except RuntimeError:
        # Expected when called outside a Temporal worker (e.g. unit tests).
        pass
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("activity_info_unavailable", activity=activity_name, error=str(exc))
    if raw_document_id is not None:
        ctx["raw_document_id"] = raw_document_id
    return ctx


# ---------------------------------------------------------------------------
# Activity: load_raw_document
# ---------------------------------------------------------------------------


@activity.defn
async def load_raw_document(raw_document_id: str) -> dict:
    """Load the raw document text and metadata from the database and object store.

    Opens a database session via ``session_factory``, reads the ``RawDocument``
    row for ``raw_document_id``, then reads the document bytes directly from
    the absolute path stored in ``raw_document.object_store_ref``.

    Note: ``LocalFileObjectStore.put()`` stores the file at an absolute path
    and returns that path as the ``object_store_ref``. We use
    ``Path(ref).read_bytes()`` to avoid any key/base-directory mismatch that
    would occur if we used ``LocalFileObjectStore.get(key)`` with a relative
    key derived from the ref.

    Args:
        raw_document_id: UUID string of the RawDocument to load.

    Returns:
        dict with keys ``text``, ``mime``, ``source_kind``, ``source_system``,
        ``source_external_id``, ``source_tier``, ``space_id``, and
        ``space_slug`` (the latter two ``None`` for a legacy row with no
        target space).
    """
    from k7e_api.models import RawDocument as RawDocumentModel
    from k7e_api.models import Space as SpaceModel

    logger.info(
        **_activity_log_context(
            "activity_started",
            "load_raw_document",
            raw_document_id=raw_document_id,
        )
    )

    with session_factory() as session:
        raw_doc = session.get(RawDocumentModel, UUID(raw_document_id))
        if raw_doc is None:
            raise ApplicationError(f"RawDocument not found: {raw_document_id}", non_retryable=True)

        # Space-routed ingest (personal or team-targeted upload/conversation):
        # join the Space row so the worker can resolve the per-space OKF
        # bundle. NULL for a legacy row with no target space.
        space_slug: str | None = None
        if raw_doc.space_id is not None:
            space = session.get(SpaceModel, raw_doc.space_id)
            space_slug = space.slug if space is not None else None

        # Binary types (PDF/images) can't be utf-8 decoded — they are
        # transcribed by extract_document_text_activity instead, which reads
        # the bytes itself (raw file payloads must never cross the Temporal
        # activity-result boundary).
        needs_extraction = raw_doc.mime_type in EXTRACTABLE_MIME
        if needs_extraction:
            text = None
        else:
            # Read bytes directly from the absolute path stored in
            # object_store_ref. This avoids a key/path mismatch with
            # LocalFileObjectStore.get(relative_key).
            data = Path(raw_doc.object_store_ref).read_bytes()
            text = data.decode("utf-8", errors="replace")

        logger.info(
            **_activity_log_context(
                "activity_completed",
                "load_raw_document",
                raw_document_id=raw_document_id,
            ),
            mime_type=raw_doc.mime_type,
            size_chars=len(text) if text else 0,
            needs_extraction=needs_extraction,
        )

        return {
            "text": text,
            "needs_extraction": needs_extraction,
            "mime": raw_doc.mime_type,
            "source_kind": "manual_upload",
            "source_system": raw_doc.source_system,
            "source_external_id": raw_doc.source_external_id,
            "source_tier": raw_doc.source_tier,
            "space_id": str(raw_doc.space_id) if raw_doc.space_id else None,
            "space_slug": space_slug,
        }


# ---------------------------------------------------------------------------
# Activity: redact_activity
# ---------------------------------------------------------------------------


@activity.defn
async def redact_activity(text: str) -> dict:
    """Apply deterministic PII redaction to the input text.

    Uses ``k7e_api.redaction.redact`` to replace emails with
    ``[REDACTED_EMAIL]`` and credit-card-like numbers with ``[REDACTED_CC]``.

    Args:
        text: The raw document text to redact.

    Returns:
        dict with keys:
        - ``redacted``: the redacted text string.
        - ``categories``: list of redacted category names (e.g. ``["email"]``).
    """
    logger.info(**_activity_log_context("activity_started", "redact_activity"))
    redacted_text, categories = redact(text)
    logger.info(
        **_activity_log_context("activity_completed", "redact_activity"),
        input_chars=len(text),
        output_chars=len(redacted_text),
        redaction_categories_count=len(categories),
    )
    return {"redacted": redacted_text, "categories": categories}
