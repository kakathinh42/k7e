"""The backfill workflow + activity are registered, and the schedule helper is idempotent."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from k7e_worker.embed_backfill import embed_backfill_activity
from k7e_worker.main import INGEST_ACTIVITIES, WORKFLOWS, ensure_backfill_schedule
from k7e_worker.workflows import EmbeddingBackfillWorkflow


def test_backfill_registered():
    assert EmbeddingBackfillWorkflow in WORKFLOWS
    assert embed_backfill_activity in INGEST_ACTIVITIES


@pytest.mark.asyncio
async def test_backfill_workflow_runs_end_to_end():
    """Execute EmbeddingBackfillWorkflow end-to-end with a stubbed activity.

    Guards against the activity being referenced in the workflow body but never
    imported (a NameError only surfaced at run time, invisible to registration
    checks). Skips if the Temporal test server binary cannot be obtained.
    """
    try:
        from temporalio import activity as act_module
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker
    except ImportError as exc:
        pytest.skip(f"temporalio not installed: {exc}")

    _STUB_RESULT = {"embedded": 3, "remaining": 0}

    @act_module.defn(name="embed_backfill_activity")
    async def _stub_backfill() -> dict:
        return _STUB_RESULT

    try:
        env = await WorkflowEnvironment.start_time_skipping()
    except Exception as exc:
        pytest.skip(f"Temporal test server unavailable (likely offline or download failed): {exc}")

    try:
        async with Worker(
            env.client,
            task_queue="test-backfill-queue",
            workflows=[EmbeddingBackfillWorkflow],
            activities=[_stub_backfill],
        ):
            result = await env.client.execute_workflow(
                EmbeddingBackfillWorkflow.run,
                id=f"backfill-test-{uuid.uuid4()}",
                task_queue="test-backfill-queue",
            )
        assert result == _STUB_RESULT
    finally:
        await env.shutdown()


async def test_ensure_schedule_creates_then_tolerates_existing():
    from temporalio.client import ScheduleAlreadyRunningError

    client = AsyncMock()
    await ensure_backfill_schedule(client, interval_seconds=120)
    client.create_schedule.assert_awaited_once()

    client.create_schedule.side_effect = ScheduleAlreadyRunningError()
    # Must NOT raise on the already-exists path.
    await ensure_backfill_schedule(client, interval_seconds=120)
