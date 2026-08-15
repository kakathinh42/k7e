"""Temporal workflow definitions for the k7e ingestion pipeline.

Defines ``IngestWorkflow`` (v2 OKF), which orchestrates autonomous ingestion:
    load_raw_document → [extract_document_text_activity] → redact_activity
        → okf_ingest_activity → okf_mirror_activity → [embed_backfill_activity]

The extract step runs only for binary uploads (PDF/PNG/JPEG): a vision LLM
transcribes them to text before redaction. The trailing embed_backfill step is
best-effort — it eagerly embeds the just-mirrored chunks so a new page is
vector-searchable within seconds; a failure is logged and swallowed (the
scheduled backfill remains the net).

The workflow is registered on the ``wiki-ingest`` task queue (``INGEST_TASK_QUEUE``
from ``k7e_api.temporal_client``).

Design notes
------------
* Activity imports are done inside the ``workflow.unsafe.imports_passed_through()``
  context manager as required by the Temporal Python SDK (workflow code runs in a
  sandbox and importing non-deterministic modules at the top level is restricted).
* Retry policies and per-activity timeouts are defined centrally in
  ``k7e_worker.retry`` via ``activity_options(name)``.
* ``okf_ingest_activity`` uses a more generous retry policy
  (``maximum_attempts=5``, longer exponential backoff) because it makes LLM calls,
  which fail transiently most often (rate limits, network, model unavailability).
"""

from __future__ import annotations

from temporalio import workflow

# Import first-party worker modules inside the sandbox-safe context
with workflow.unsafe.imports_passed_through():
    from temporalio.exceptions import is_cancelled_exception

    from k7e_worker.activities import load_raw_document, redact_activity
    from k7e_worker.embed_backfill import embed_backfill_activity
    from k7e_worker.extract_activities import extract_document_text_activity
    from k7e_worker.okf_activities import (
        okf_ingest_activity,
        okf_mirror_activity,
    )
    from k7e_worker.retry import activity_options


@workflow.defn
class IngestWorkflow:
    """v2 OKF ingest — one autonomous pipeline for every source.

    Execution order:
    1. ``load_raw_document`` – fetch source text + metadata (binary uploads
       return ``text=None, needs_extraction=True``).
    2. ``extract_document_text_activity`` – vision-transcribe PDF/image bytes
       to text (only when ``needs_extraction``).
    3. ``redact_activity`` – replace PII with placeholders.
    4. ``okf_ingest_activity`` – two-pass ingest: the LLM writes typed OKF pages
       (source / entity / concept) and ``[[wikilinks]]`` them, committed to the
       git bundle.
    5. ``okf_mirror_activity`` – mirror the bundle into Postgres for search + graph.
    6. ``embed_backfill_activity`` (best-effort) – eagerly embed the just-mirrored
       chunks so a new page is vector-searchable within seconds; failures are
       logged and swallowed (the scheduled backfill remains the net).

    No gate, no review, no Tier-A/B branch. Returns the ingest summary
    (``source_slug``, ``pages``, ``commit``).

    Space routing (Task 9): ``load_raw_document`` returns ``space_id``/
    ``space_slug`` (both ``None`` for a legacy/unrouted source, so pre-upgrade
    workflow histories replay unchanged). These are threaded straight through
    — pure data from a prior activity result, no config/I-O/wall-clock lookups
    here — into ``okf_ingest_activity``/``okf_mirror_activity``, which resolve
    the per-space OKF bundle themselves.
    """

    @workflow.run
    async def run(self, raw_document_id: str) -> dict:
        load_result: dict = await workflow.execute_activity(
            load_raw_document,
            raw_document_id,
            **activity_options("load_raw_document"),
        )

        # Binary uploads (PDF/images) carry no decodable text — a vision LLM
        # transcribes them first. Deterministic: branches only on activity
        # results. Redaction then runs on the extracted text as usual.
        if load_result.get("needs_extraction"):
            extract_result: dict = await workflow.execute_activity(
                extract_document_text_activity,
                raw_document_id,
                **activity_options("extract_document_text_activity"),
            )
            text = extract_result["text"]
        else:
            text = load_result["text"]

        redact_result: dict = await workflow.execute_activity(
            redact_activity,
            text,
            **activity_options("redact_activity"),
        )

        source = {"source_uri": load_result.get("source_external_id")}
        space_id = load_result.get("space_id")
        space_slug = load_result.get("space_slug")
        ingest_result: dict = await workflow.execute_activity(
            okf_ingest_activity,
            args=[redact_result["redacted"], raw_document_id, source, space_slug],
            **activity_options("okf_ingest_activity"),
        )

        await workflow.execute_activity(
            okf_mirror_activity,
            args=[space_id, space_slug],
            **activity_options("okf_mirror_activity"),
        )
        # P0: eagerly embed the just-mirrored chunks so a new page is
        # vector-searchable within seconds instead of on the next scheduled
        # backfill tick. Best-effort — a failure here must never fail the
        # ingest; the periodic embedding-backfill schedule remains the net.
        # Deterministic: branches only on activity success/failure.
        try:
            await workflow.execute_activity(
                embed_backfill_activity,
                **activity_options("embed_backfill_activity"),
            )
        except Exception as exc:  # noqa: BLE001 — scheduled backfill catches up
            # A workflow cancellation surfaces here as an ActivityError whose
            # cause is CancelledError; that must propagate so the workflow ends
            # Cancelled rather than completing normally. Only genuine backfill
            # failures are swallowed.
            if is_cancelled_exception(exc):
                raise
            workflow.logger.warning("post-ingest embed kick failed; leaving to scheduled backfill")
        return ingest_result


@workflow.defn
class EmbeddingBackfillWorkflow:
    """Fire one bounded embedding-backfill batch. Triggered by a Temporal Schedule."""

    @workflow.run
    async def run(self) -> dict:
        return await workflow.execute_activity(
            embed_backfill_activity,
            **activity_options("embed_backfill_activity"),
        )
