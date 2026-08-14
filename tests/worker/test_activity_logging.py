"""Tests for k7e_worker.activities structured logging.

Covers:
1. _activity_log_context returns base fields and omits Temporal fields
   when no activity context is available (no exception raised).
2. _activity_log_context includes raw_document_id when provided.
3. _activity_log_context includes workflow/run/activity/attempt when
   activity.info() is stubbed (the success branch).
4. redact_activity emits exactly one activity_started and one
   activity_completed event with documented safe fields.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from structlog.testing import capture_logs


def _unwrap_activity(fn):
    if hasattr(fn, "fn"):
        return fn.fn
    if hasattr(fn, "__wrapped__"):
        return fn.__wrapped__
    return fn


def test_activity_log_context_without_worker_context():
    """Outside a worker, activity.info() raises; helper must omit Temporal
    fields, never raise, and still return event/activity keys."""
    from k7e_worker.activities import _activity_log_context

    ctx = _activity_log_context("activity_started", "redact_activity")

    assert ctx["event"] == "activity_started"
    assert ctx["activity"] == "redact_activity"
    for forbidden in ("workflow_id", "workflow_run_id", "activity_id", "attempt"):
        assert forbidden not in ctx, f"{forbidden} must not be present outside worker"
    assert "raw_document_id" not in ctx


def test_activity_log_context_includes_raw_document_id_when_provided():
    from k7e_worker.activities import _activity_log_context

    ctx = _activity_log_context(
        "activity_started",
        "load_raw_document",
        raw_document_id="00000000-0000-0000-0000-000000000001",
    )

    assert ctx["raw_document_id"] == "00000000-0000-0000-0000-000000000001"
    assert ctx["event"] == "activity_started"
    assert ctx["activity"] == "load_raw_document"


def test_activity_log_context_includes_temporal_fields_when_info_available(monkeypatch):
    """When activity.info() returns a real-looking object, all four Temporal
    fields appear in the context dict."""
    import k7e_worker.activities as act_module

    fake_info = SimpleNamespace(
        workflow_id="wf-abc",
        workflow_run_id="run-xyz",
        activity_id="act-1",
        attempt=2,
        activity_type="redact_activity",
    )
    monkeypatch.setattr(act_module.activity, "info", lambda: fake_info)

    ctx = act_module._activity_log_context("activity_completed", "redact_activity")

    assert ctx["workflow_id"] == "wf-abc"
    assert ctx["workflow_run_id"] == "run-xyz"
    assert ctx["activity_id"] == "act-1"
    assert ctx["attempt"] == 2
    assert ctx["event"] == "activity_completed"
    assert ctx["activity"] == "redact_activity"


@pytest.mark.asyncio
async def test_redact_activity_emits_started_and_completed_events():
    from k7e_worker.activities import redact_activity

    fn = _unwrap_activity(redact_activity)

    with capture_logs() as cap:
        result = await fn("Contact user@example.com for help.")

    assert "[REDACTED_EMAIL]" in result["redacted"]

    started = [
        e
        for e in cap
        if e.get("event") == "activity_started" and e.get("activity") == "redact_activity"
    ]
    completed = [
        e
        for e in cap
        if e.get("event") == "activity_completed" and e.get("activity") == "redact_activity"
    ]

    assert len(started) == 1, f"expected exactly 1 started event, got {len(started)}: {cap}"
    assert len(completed) == 1, f"expected exactly 1 completed event, got {len(completed)}: {cap}"

    done = completed[0]
    assert done["input_chars"] == len("Contact user@example.com for help.")
    assert done["output_chars"] == len(result["redacted"])
    assert done["redaction_categories_count"] == len(result["categories"])
