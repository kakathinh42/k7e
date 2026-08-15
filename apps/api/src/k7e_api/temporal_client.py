"""Temporal client seam for the k7e API (Task 4.1).

Responsibilities:
- Expose ``INGEST_TASK_QUEUE`` constant used by the API to start workflows.
- Provide ``get_temporal_client()`` which connects to the configured Temporal
  server; this is called at *runtime* only, never at import time.
- Provide ``start_ingest_workflow(raw_document_id)`` which starts the
  ``IngestWorkflow`` on the ingest task queue and returns the workflow id.

Design notes:
- The ``temporalio`` package is imported at module top-level (fine; the SDK
  does not attempt to connect on import).  *Connecting* only happens inside
  ``get_temporal_client()``.
- Tests monkeypatch ``get_temporal_client`` in this module to avoid any real
  network calls; the production function is never invoked during the test suite.
"""

from __future__ import annotations

from temporalio.client import Client

from k7e_api.config import get_settings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INGEST_TASK_QUEUE: str = "wiki-ingest"
"""Temporal task queue name shared by the API (producer) and worker (consumer)."""


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------


async def get_temporal_client() -> Client:
    """Connect to the Temporal server and return the client.

    The host is read from ``Settings.temporal_host`` (default
    ``localhost:7233``).  This function performs a network call and must
    **not** be invoked at module import time.

    Returns:
        A connected :class:`temporalio.client.Client` instance.
    """
    host = get_settings().temporal_host
    return await Client.connect(host)


# ---------------------------------------------------------------------------
# Workflow starter
# ---------------------------------------------------------------------------


async def start_ingest_workflow(raw_document_id: str) -> str:
    """Start the ``IngestWorkflow`` for the given raw document and return its id.

    Uses the string-name form of ``client.start_workflow`` so that this module
    does **not** need to import the workflow class (which lives in the worker
    package).

    Args:
        raw_document_id: The UUID string of the ``RawDocument`` row to process.

    Returns:
        The Temporal workflow id, e.g. ``"ingest-<raw_document_id>"``.
    """
    client = await get_temporal_client()
    workflow_id = f"ingest-{raw_document_id}"
    await client.start_workflow(
        "IngestWorkflow",
        raw_document_id,
        id=workflow_id,
        task_queue=INGEST_TASK_QUEUE,
    )
    return workflow_id
