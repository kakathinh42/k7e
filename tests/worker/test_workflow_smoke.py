"""Smoke test for the v2 OKF IngestWorkflow using Temporal's test environment.

This test:
1. Starts the Temporal time-skipping test server (downloads a binary on first use).
2. Registers IngestWorkflow with stubbed activities that return canned dicts.
3. Executes the workflow with a fake raw_document_id.
4. Asserts the workflow returns the OKF ingest summary unchanged.

If the Temporal test server binary cannot be downloaded (offline environment,
network error, or runtime issues), the test SKIPS gracefully rather than
failing. This ensures the test suite passes in offline/CI environments that
lack internet access for the binary download.
"""

from __future__ import annotations

import uuid

import pytest

# ---------------------------------------------------------------------------
# Canned stub responses for each activity
# ---------------------------------------------------------------------------

_FAKE_RAW_DOCUMENT_ID = str(uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"))

_STUB_LOAD_RESULT = {
    "text": "# Hello World\n\nThis is a test document.",
    "mime": "text/markdown",
    "source_kind": "manual_upload",
    "source_external_id": "doc://hello-world",
}

_STUB_REDACT_RESULT = {
    "redacted": "# Hello World\n\nThis is a test document.",
    "categories": [],
}

_STUB_INGEST_RESULT = {
    "source_slug": "hello-world",
    "pages": ["sources/hello-world", "concepts/testing"],
    "commit": "abc1234",
}

_STUB_MIRROR_RESULT = {
    "pages": 2,
    "links": 1,
}


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_workflow_smoke():
    """Run the OKF IngestWorkflow end-to-end with stubbed activities.

    Skips if the Temporal test server binary cannot be obtained (offline).
    """
    try:
        from temporalio import activity as act_module
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker
    except ImportError as exc:
        pytest.skip(f"temporalio not installed: {exc}")

    try:
        from k7e_worker.workflows import IngestWorkflow
    except ImportError as exc:
        pytest.skip(f"k7e_worker.workflows not yet implemented: {exc}")

    # Stub the four activities the OKF workflow invokes, by their production names.
    @act_module.defn(name="load_raw_document")
    async def _stub_load(raw_document_id: str) -> dict:
        return _STUB_LOAD_RESULT

    @act_module.defn(name="redact_activity")
    async def _stub_redact(text: str) -> dict:
        return _STUB_REDACT_RESULT

    @act_module.defn(name="okf_ingest_activity")
    async def _stub_ingest(
        redacted_text: str,
        raw_document_id: str,
        source: dict | None = None,
        space_slug: str | None = None,
    ) -> dict:
        return _STUB_INGEST_RESULT

    @act_module.defn(name="okf_mirror_activity")
    async def _stub_mirror(space_id: str | None = None, space_slug: str | None = None) -> dict:
        return _STUB_MIRROR_RESULT

    @act_module.defn(name="embed_backfill_activity")
    async def _stub_backfill() -> dict:
        return {"embedded": 0, "remaining": 0}

    stub_activities = [
        _stub_load,
        _stub_redact,
        _stub_ingest,
        _stub_mirror,
        _stub_backfill,
    ]

    try:
        env = await WorkflowEnvironment.start_time_skipping()
    except Exception as exc:
        pytest.skip(f"Temporal test server unavailable (likely offline or download failed): {exc}")

    try:
        async with Worker(
            env.client,
            task_queue="test-ingest-queue",
            workflows=[IngestWorkflow],
            activities=stub_activities,
        ):
            result = await env.client.execute_workflow(
                IngestWorkflow.run,
                _FAKE_RAW_DOCUMENT_ID,
                id=f"smoke-test-{uuid.uuid4()}",
                task_queue="test-ingest-queue",
            )

        # The workflow returns the OKF ingest summary verbatim.
        assert isinstance(result, dict), f"Expected dict result, got {type(result)}"
        assert result["source_slug"] == "hello-world"
        assert result["pages"] == _STUB_INGEST_RESULT["pages"]
        assert result["commit"] == "abc1234"
    finally:
        await env.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("needs_extraction", [False, True])
async def test_ingest_workflow_extraction_branch(needs_extraction):
    """Binary documents route through extract_document_text_activity; text skips it.

    Skips if the Temporal test server binary cannot be obtained (offline).
    """
    try:
        from temporalio import activity as act_module
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker
    except ImportError as exc:
        pytest.skip(f"temporalio not installed: {exc}")

    from k7e_worker.workflows import IngestWorkflow

    extract_calls: list[str] = []
    redact_inputs: list[str] = []

    if needs_extraction:
        load_result = {
            "text": None,
            "needs_extraction": True,
            "mime": "application/pdf",
            "source_kind": "manual_upload",
            "source_external_id": "doc://spec-pdf",
        }
    else:
        load_result = _STUB_LOAD_RESULT

    @act_module.defn(name="load_raw_document")
    async def _stub_load(raw_document_id: str) -> dict:
        return load_result

    @act_module.defn(name="extract_document_text_activity")
    async def _stub_extract(raw_document_id: str) -> dict:
        extract_calls.append(raw_document_id)
        return {
            "text": "Extracted PDF text.",
            "page_count": 2,
            "transcribed_pages": 2,
            "truncated": False,
        }

    @act_module.defn(name="redact_activity")
    async def _stub_redact(text: str) -> dict:
        redact_inputs.append(text)
        return {"redacted": text, "categories": []}

    @act_module.defn(name="okf_ingest_activity")
    async def _stub_ingest(
        redacted_text: str,
        raw_document_id: str,
        source: dict | None = None,
        space_slug: str | None = None,
    ) -> dict:
        return _STUB_INGEST_RESULT

    @act_module.defn(name="okf_mirror_activity")
    async def _stub_mirror(space_id: str | None = None, space_slug: str | None = None) -> dict:
        return _STUB_MIRROR_RESULT

    @act_module.defn(name="embed_backfill_activity")
    async def _stub_backfill() -> dict:
        return {"embedded": 0, "remaining": 0}

    try:
        env = await WorkflowEnvironment.start_time_skipping()
    except Exception as exc:
        pytest.skip(f"Temporal test server unavailable (likely offline or download failed): {exc}")

    try:
        async with Worker(
            env.client,
            task_queue="test-ingest-queue",
            workflows=[IngestWorkflow],
            activities=[
                _stub_load,
                _stub_extract,
                _stub_redact,
                _stub_ingest,
                _stub_mirror,
                _stub_backfill,
            ],
        ):
            await env.client.execute_workflow(
                IngestWorkflow.run,
                _FAKE_RAW_DOCUMENT_ID,
                id=f"smoke-test-{uuid.uuid4()}",
                task_queue="test-ingest-queue",
            )

        if needs_extraction:
            assert extract_calls == [_FAKE_RAW_DOCUMENT_ID]
            assert redact_inputs == ["Extracted PDF text."]
        else:
            assert extract_calls == []
            assert redact_inputs == [_STUB_LOAD_RESULT["text"]]
    finally:
        await env.shutdown()
