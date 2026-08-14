"""Vision-extraction activity: transcribe a binary raw document into text.

Sits between ``load_raw_document`` and ``redact_activity`` in the ingest
workflow, only for PDF/image uploads. Mirrors ``okf_activities.py``: LLM-
calling activity kept separate from the deterministic ones, with the same
``session_factory`` / ``llm_client_factory`` module seams for tests.

The activity receives only the raw-document id and reads the bytes from the
object store itself — raw file payloads must never cross the Temporal
activity boundary (~2 MB payload limit).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable
from uuid import UUID

from k7e_api.config import get_settings
from k7e_api.db import SessionLocal
from k7e_api.extraction import ExtractionError, extract_text
from k7e_api.ingest_history import record_ingest_run
from k7e_api.llm_client import LiteLLMClient
from k7e_api.logging_setup import get_logger
from k7e_api.validation import EXTRACTABLE_MIME
from temporalio import activity
from temporalio.exceptions import ApplicationError

session_factory = SessionLocal
llm_client_factory: Callable = LiteLLMClient
logger = get_logger(__name__)


def _heartbeat(page_n: int) -> None:
    """Heartbeat before each vision call; silent outside a Temporal worker."""
    try:
        activity.heartbeat(page_n)
    except RuntimeError:
        pass  # direct-call unit tests run without an activity context


@activity.defn
async def extract_document_text_activity(raw_document_id: str) -> dict:
    """Vision-transcribe a binary raw document (PDF/PNG/JPEG) into text.

    Stateless and idempotent: a retry re-pays every page transcription, which
    is accepted at the max_pdf_pages cap. Unreadable input or an all-blank
    transcription is non-retryable; transient vision-call failures propagate
    so Temporal retries the activity.

    Returns:
        dict with keys ``text``, ``page_count``, ``transcribed_pages``,
        ``truncated``.
    """
    from k7e_api.models import RawDocument as RawDocumentModel

    logger.info(
        "activity_started",
        activity="extract_document_text_activity",
        raw_document_id=raw_document_id,
    )
    settings = get_settings()

    with session_factory() as session:
        raw_doc = session.get(RawDocumentModel, UUID(raw_document_id))
        if raw_doc is None:
            raise ApplicationError(f"RawDocument not found: {raw_document_id}", non_retryable=True)
        mime = raw_doc.mime_type
        if mime not in EXTRACTABLE_MIME:
            raise ApplicationError(
                f"document is not vision-extractable (mime={mime}); "
                "the workflow should not have routed it here",
                non_retryable=True,
            )
        data = Path(raw_doc.object_store_ref).read_bytes()

    client = llm_client_factory()
    try:
        result = await extract_text(
            data,
            mime,
            client=client,
            max_pdf_pages=settings.max_pdf_pages,
            on_page=_heartbeat,
        )
    except ExtractionError as exc:
        raise ApplicationError(str(exc), non_retryable=True) from exc

    # Accounting + metadata are best-effort — never fail a successful
    # extraction over them (same contract as okf_ingest_activity).
    usage = getattr(client, "usage", None)
    tokens = usage.get("total_tokens") if usage else None
    try:
        with session_factory() as session:
            if usage:
                record_ingest_run(
                    session,
                    raw_document_id=raw_document_id,
                    source_slug=None,
                    page_count=result.page_count,
                    usage=usage,
                    model_id=settings.wiki_vision_model,
                    settings=settings,
                )
            raw_doc = session.get(RawDocumentModel, UUID(raw_document_id))
            if raw_doc is not None:
                # Reassign (not mutate): JSON columns don't detect in-place changes.
                raw_doc.extra_metadata = {
                    **(raw_doc.extra_metadata or {}),
                    "extraction": {
                        "transcribed_pages": result.transcribed_pages,
                        "truncated": result.truncated,
                        "vision_model": settings.wiki_vision_model,
                        "chars": len(result.text),
                    },
                }
                session.commit()
    except Exception as exc:  # noqa: BLE001 - accounting is not load-bearing
        logger.warning("extract_accounting_failed", error=str(exc))

    logger.info(
        "activity_completed",
        activity="extract_document_text_activity",
        raw_document_id=raw_document_id,
        page_count=result.page_count,
        transcribed_pages=result.transcribed_pages,
        truncated=result.truncated,
        tokens=tokens,
        size_chars=len(result.text),
    )
    return {
        "text": result.text,
        "page_count": result.page_count,
        "transcribed_pages": result.transcribed_pages,
        "truncated": result.truncated,
    }
