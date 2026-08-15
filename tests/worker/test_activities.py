"""Tests for k7e_worker.activities – the deterministic front-of-pipeline activities.

All tests run WITHOUT a Temporal server and WITHOUT a PostgreSQL instance.
Activities decorated with @activity.defn are called directly (outside a worker
context); the temporalio SDK allows calling the underlying function via `.fn`.

Covers:
1. redact_activity: redacted text + categories for input containing an email.
2. redact_activity: clean input returns empty categories.

(load_raw_document is exercised end-to-end by the workflow smoke + live tests;
the v2 OKF ingest activities are covered in tests/api/test_okf_*.)
"""

from __future__ import annotations

import pytest


def _unwrap_activity(fn):
    """Return the underlying coroutine function for an @activity.defn function."""
    if hasattr(fn, "fn"):
        return fn.fn
    if hasattr(fn, "__wrapped__"):
        return fn.__wrapped__
    return fn


@pytest.mark.asyncio
async def test_redact_activity_replaces_email():
    """redact_activity must replace emails and return category 'email'."""
    from k7e_worker.activities import redact_activity

    fn = _unwrap_activity(redact_activity)
    result = await fn("Contact us at user@example.com for help.")

    assert isinstance(result, dict), "Expected dict result"
    assert "redacted" in result
    assert "categories" in result
    assert "[REDACTED_EMAIL]" in result["redacted"]
    assert "user@example.com" not in result["redacted"]
    assert "email" in result["categories"]


@pytest.mark.asyncio
async def test_redact_activity_no_sensitive_data():
    """redact_activity with clean input returns empty categories."""
    from k7e_worker.activities import redact_activity

    fn = _unwrap_activity(redact_activity)
    result = await fn("Hello world, no sensitive data here.")

    assert result["categories"] == []
    assert result["redacted"] == "Hello world, no sensitive data here."
