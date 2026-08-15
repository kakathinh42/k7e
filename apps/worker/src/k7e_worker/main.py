"""Worker entry point for the k7e ingestion pipeline.

Connects to the Temporal server and runs a worker on the ``wiki-ingest``
task queue with the ``IngestWorkflow`` and all its activities registered.

Usage:
    python -m k7e_worker.main
    # or:
    wiki-worker  # if installed as a script

The Temporal server host is read from ``Settings.temporal_host``
(default: ``localhost:7233``).

Uses ``k7e_api.temporal_client.get_temporal_client()`` as the single seam
for creating the Temporal client, consistent with the API tier.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

from k7e_api.config import get_settings
from k7e_api.logging_setup import configure_logging, get_logger
from k7e_api.temporal_client import INGEST_TASK_QUEUE, get_temporal_client
from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleIntervalSpec,
    ScheduleSpec,
)
from temporalio.service import RPCError, RPCStatusCode
from temporalio.worker import Worker

from k7e_worker.activities import load_raw_document, redact_activity
from k7e_worker.embed_backfill import embed_backfill_activity
from k7e_worker.extract_activities import extract_document_text_activity
from k7e_worker.okf_activities import (
    okf_ingest_activity,
    okf_mirror_activity,
)
from k7e_worker.workflows import EmbeddingBackfillWorkflow, IngestWorkflow

# Every activity a workflow can invoke must be registered here, or the Temporal
# worker raises NotFoundError at runtime. Kept as a module-level constant so a
# test can assert coverage against the activities the workflow references.
INGEST_ACTIVITIES = [
    load_raw_document,
    extract_document_text_activity,
    redact_activity,
    okf_ingest_activity,
    okf_mirror_activity,
    embed_backfill_activity,
]

WORKFLOWS = [IngestWorkflow, EmbeddingBackfillWorkflow]


async def ensure_backfill_schedule(client, *, interval_seconds: int) -> None:
    """Create the embedding-backfill Temporal Schedule if it doesn't exist."""
    try:
        await client.create_schedule(
            "embedding-backfill",
            Schedule(
                action=ScheduleActionStartWorkflow(
                    EmbeddingBackfillWorkflow.run,
                    id="embedding-backfill-wf",
                    task_queue=INGEST_TASK_QUEUE,
                ),
                spec=ScheduleSpec(
                    intervals=[ScheduleIntervalSpec(every=timedelta(seconds=interval_seconds))]
                ),
            ),
        )
    except ScheduleAlreadyRunningError:
        return
    except RPCError as exc:
        if exc.status == RPCStatusCode.ALREADY_EXISTS:
            return
        raise


async def _main() -> None:
    """Connect to Temporal and run the worker until shutdown."""
    # Configure structlog once, before any activity can run. Reuses the API's
    # JSON logging contract so worker and API share an identical log format.
    configure_logging()
    logger = get_logger(__name__)

    # Reuse the shared client factory from the API seam for DRY consistency.
    client = await get_temporal_client()

    worker = Worker(
        client,
        task_queue=INGEST_TASK_QUEUE,
        workflows=WORKFLOWS,
        activities=INGEST_ACTIVITIES,
    )

    # Idempotently register the recurring embedding-backfill schedule. Safe to
    # call on every worker startup: an ALREADY_EXISTS error is swallowed.
    await ensure_backfill_schedule(
        client, interval_seconds=get_settings().embed_backfill_interval_seconds
    )

    logger.info(event="worker_started", task_queue=INGEST_TASK_QUEUE)

    # Startup readiness signal for the container healthcheck (the worker has no
    # HTTP surface). Ongoing liveness relies on the container restart policy.
    Path("/tmp/worker_ready").touch()

    await worker.run()


def run() -> None:
    """Synchronous entry point; runs the async worker via asyncio.run()."""
    asyncio.run(_main())


if __name__ == "__main__":
    run()
