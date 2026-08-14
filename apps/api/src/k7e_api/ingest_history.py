"""Per-ingest token usage + estimated $ cost — recording and pricing.

Each OKF ingest activity makes several LLM calls (extract, relate, one compose
per page). The LLM client accumulates token ``usage`` across them; this module
turns that usage into a dollar estimate and persists one ``IngestRun`` row so the
upload-history UI can show "this file cost N tokens / $X to compile".
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from k7e_api.config import Settings, get_settings
from k7e_api.models import IngestRun, RawDocument


def estimate_cost_usd(usage: dict, settings: Settings | None = None) -> float:
    """Estimate the $ cost of a token usage dict from the configured per-Mtok rates."""
    settings = settings or get_settings()
    cost = (
        usage.get("prompt_tokens", 0) / 1_000_000 * settings.llm_cost_input_usd_per_mtok
        + usage.get("completion_tokens", 0) / 1_000_000 * settings.llm_cost_output_usd_per_mtok
    )
    return round(cost, 6)


def record_ingest_run(
    session: Session,
    *,
    raw_document_id: str | None,
    source_slug: str | None,
    page_count: int,
    usage: dict,
    model_id: str,
    settings: Settings | None = None,
) -> IngestRun:
    """Persist one ``IngestRun`` row from a completed ingest. Commits the session."""
    settings = settings or get_settings()

    filename = ""
    rid: uuid.UUID | None = None
    doc: RawDocument | None = None
    if raw_document_id:
        try:
            rid = uuid.UUID(raw_document_id)
        except (ValueError, AttributeError):
            rid = None
        if rid is not None:
            doc = session.get(RawDocument, rid)
            if doc is not None:
                filename = doc.filename

    run = IngestRun(
        raw_document_id=rid,
        filename=filename,
        source_slug=source_slug,
        model_id=model_id,
        prompt_tokens=int(usage.get("prompt_tokens", 0)),
        completion_tokens=int(usage.get("completion_tokens", 0)),
        total_tokens=int(usage.get("total_tokens", 0)),
        llm_calls=int(usage.get("calls", 0)),
        cost_usd=estimate_cost_usd(usage, settings),
        page_count=page_count,
        org_id=doc.org_id if doc is not None else None,
    )
    session.add(run)
    session.commit()
    return run
