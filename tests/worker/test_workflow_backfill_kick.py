"""P0: IngestWorkflow eagerly kicks embed_backfill after mirror (best-effort)."""

from __future__ import annotations

import asyncio
import uuid

import pytest

_FAKE_RAW_DOCUMENT_ID = str(uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"))

_STUB_LOAD = {
    "text": "# Hello\n\nBody.",
    "mime": "text/markdown",
    "source_kind": "manual_upload",
    "source_external_id": "doc://hello",
}
_STUB_REDACT = {"redacted": "# Hello\n\nBody.", "categories": []}
_STUB_INGEST = {"source_slug": "hello", "pages": ["sources/hello"], "commit": "c0ffee0"}
_STUB_MIRROR = {"pages": 1, "links": 0}


async def _run(calls, backfill_impl):
    """Run IngestWorkflow with stubbed activities; return the result dict.

    ``backfill_impl`` is the coroutine body for the embed_backfill stub;
    ``calls`` records ordering so tests can assert the kick fired after mirror.
    Skips if the Temporal test server binary is unavailable (offline).
    """
    try:
        from temporalio import activity as act_module
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker
    except ImportError as exc:
        pytest.skip(f"temporalio not installed: {exc}")

    from k7e_worker.workflows import IngestWorkflow

    @act_module.defn(name="load_raw_document")
    async def _load(raw_document_id: str) -> dict:
        return _STUB_LOAD

    @act_module.defn(name="redact_activity")
    async def _redact(text: str) -> dict:
        return _STUB_REDACT

    @act_module.defn(name="okf_ingest_activity")
    async def _ingest(redacted_text, raw_document_id, source=None, space_slug=None) -> dict:
        return _STUB_INGEST

    @act_module.defn(name="okf_mirror_activity")
    async def _mirror(space_id=None, space_slug=None) -> dict:
        calls.append("mirror")
        return _STUB_MIRROR

    @act_module.defn(name="embed_backfill_activity")
    async def _backfill() -> dict:
        calls.append("backfill")
        return await backfill_impl()

    try:
        env = await WorkflowEnvironment.start_time_skipping()
    except Exception as exc:
        pytest.skip(f"Temporal test server unavailable: {exc}")

    try:
        async with Worker(
            env.client,
            task_queue="test-ingest-queue",
            workflows=[IngestWorkflow],
            activities=[_load, _redact, _ingest, _mirror, _backfill],
        ):
            return await env.client.execute_workflow(
                IngestWorkflow.run,
                _FAKE_RAW_DOCUMENT_ID,
                id=f"kick-test-{uuid.uuid4()}",
                task_queue="test-ingest-queue",
            )
    finally:
        await env.shutdown()


async def test_ingest_kicks_backfill_after_mirror():
    calls: list[str] = []

    async def _ok():
        return {"embedded": 1, "remaining": 0}

    result = await _run(calls, _ok)
    assert result["source_slug"] == "hello"
    # The kick fires, and only after the mirror committed.
    assert "backfill" in calls
    assert calls.index("mirror") < calls.index("backfill")


async def test_ingest_tolerates_backfill_failure():
    calls: list[str] = []

    async def _boom():
        raise RuntimeError("gateway 429")

    # Best-effort: the backfill is attempted and raises, yet the ingest
    # still returns its summary (the scheduled backfill remains the net).
    result = await _run(calls, _boom)
    assert "backfill" in calls
    assert result["source_slug"] == "hello"


async def test_ingest_cancellation_propagates_through_embed_kick():
    """A cancel landing while the embed kick is in flight must NOT be swallowed.

    The best-effort ``except Exception`` around the kick would otherwise absorb
    the cancellation (which surfaces as an ActivityError whose cause is a
    CancelledError) and let the workflow complete normally. The ``is_cancelled_
    exception`` guard re-raises so the workflow ends Cancelled — this asserts
    that a user-initiated cancel actually cancels the run.
    """
    try:
        from temporalio import activity as act_module
        from temporalio.client import WorkflowFailureError
        from temporalio.exceptions import CancelledError
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker
    except ImportError as exc:
        pytest.skip(f"temporalio not installed: {exc}")

    from k7e_worker.workflows import IngestWorkflow

    backfill_started = asyncio.Event()

    @act_module.defn(name="load_raw_document")
    async def _load(raw_document_id: str) -> dict:
        return _STUB_LOAD

    @act_module.defn(name="redact_activity")
    async def _redact(text: str) -> dict:
        return _STUB_REDACT

    @act_module.defn(name="okf_ingest_activity")
    async def _ingest(redacted_text, raw_document_id, source=None, space_slug=None) -> dict:
        return _STUB_INGEST

    @act_module.defn(name="okf_mirror_activity")
    async def _mirror(space_id=None, space_slug=None) -> dict:
        return _STUB_MIRROR

    @act_module.defn(name="embed_backfill_activity")
    async def _backfill() -> dict:
        # Signal that we're in flight, then block so the cancel lands while the
        # activity is still outstanding. The default TRY_CANCEL semantics let
        # the workflow resolve the activity as cancelled without us returning.
        backfill_started.set()
        await asyncio.sleep(3600)
        return {"embedded": 0, "remaining": 0}

    try:
        env = await WorkflowEnvironment.start_time_skipping()
    except Exception as exc:
        pytest.skip(f"Temporal test server unavailable: {exc}")

    try:
        async with Worker(
            env.client,
            task_queue="test-ingest-queue",
            workflows=[IngestWorkflow],
            activities=[_load, _redact, _ingest, _mirror, _backfill],
        ):
            handle = await env.client.start_workflow(
                IngestWorkflow.run,
                _FAKE_RAW_DOCUMENT_ID,
                id=f"cancel-test-{uuid.uuid4()}",
                task_queue="test-ingest-queue",
            )
            # Wait until the embed kick is actually running before cancelling,
            # so the cancel is delivered while the activity is outstanding.
            await asyncio.wait_for(backfill_started.wait(), timeout=30)
            await handle.cancel()

            with pytest.raises(WorkflowFailureError) as excinfo:
                await handle.result()
            # The terminal failure is a cancellation, not a normal completion.
            assert isinstance(excinfo.value.cause, CancelledError)
    finally:
        await env.shutdown()
