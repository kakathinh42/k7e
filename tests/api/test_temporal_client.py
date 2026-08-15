"""Tests for k7e_api.temporal_client (Task 4.1).

TDD: tests written before implementation to drive the design.

These tests must NOT connect to a real Temporal server.  The production
``get_temporal_client`` is monkeypatched with a fake client whose
``start_workflow`` method is an async coroutine, so we can verify the
correct workflow name, id, task_queue, and argument are passed.

Test cases:
- test_ingest_task_queue_constant
    Assert the module-level constant equals "wiki-ingest".
- test_start_ingest_workflow_uses_expected_id_and_queue
    Monkeypatch get_temporal_client; call start_ingest_workflow("abc-123");
    assert return value and recorded call args.
"""

from __future__ import annotations

import pytest
from k7e_api.temporal_client import INGEST_TASK_QUEUE, start_ingest_workflow

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeHandle:
    """Minimal stand-in for a Temporal WorkflowHandle."""


class _FakeClient:
    """Fake Temporal client that records start_workflow calls without connecting."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def start_workflow(
        self, name: str, arg: str, *, id: str, task_queue: str
    ) -> _FakeHandle:
        self.calls.append(
            {
                "name": name,
                "arg": arg,
                "id": id,
                "task_queue": task_queue,
            }
        )
        return _FakeHandle()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_ingest_task_queue_constant():
    """INGEST_TASK_QUEUE must equal 'wiki-ingest'."""
    assert INGEST_TASK_QUEUE == "wiki-ingest"


@pytest.mark.anyio
async def test_start_ingest_workflow_uses_expected_id_and_queue(monkeypatch):
    """start_ingest_workflow must:
    - call get_temporal_client() to obtain a client
    - call client.start_workflow with the correct name, arg, id, and task_queue
    - return the workflow id string "ingest-<raw_document_id>"
    """
    fake_client = _FakeClient()

    # Monkeypatch get_temporal_client to be an async function returning our fake.
    async def fake_get_temporal_client():
        return fake_client

    import k7e_api.temporal_client as tc_module

    monkeypatch.setattr(tc_module, "get_temporal_client", fake_get_temporal_client)

    result = await start_ingest_workflow("abc-123")

    # Return value must be the workflow id string
    assert result == "ingest-abc-123"

    # Exactly one start_workflow call must have been recorded
    assert len(fake_client.calls) == 1
    call = fake_client.calls[0]
    assert call["name"] == "IngestWorkflow"
    assert call["arg"] == "abc-123"
    assert call["id"] == "ingest-abc-123"
    assert call["task_queue"] == "wiki-ingest"
