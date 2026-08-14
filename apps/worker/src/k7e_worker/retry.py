"""Shared Temporal retry policies + per-activity timeouts.

`activity_options(name)` returns the kwargs to splat into
`workflow.execute_activity(...)` so every activity gets a timeout and a
retry policy from one place.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio.common import RetryPolicy

DEFAULT_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=3,
)

# LLM calls fail transiently more often (rate limits, gateway blips).
INTERPRET_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=60),
    maximum_attempts=5,
)

_TIMEOUTS: dict[str, timedelta] = {
    "load_raw_document": timedelta(seconds=30),
    # Vision extraction: up to max_pdf_pages sequential vision calls.
    "extract_document_text_activity": timedelta(seconds=900),
    "redact_activity": timedelta(seconds=15),
    # v2 OKF: extract (1 call) + compose (one call per typed page).
    "okf_ingest_activity": timedelta(seconds=600),
    # Embed every page in the bundle.
    "okf_mirror_activity": timedelta(seconds=300),
    # One bounded batch of embeddings; fail-fast so it never approaches this.
    "embed_backfill_activity": timedelta(seconds=120),
}

_POLICIES: dict[str, RetryPolicy] = {
    "okf_ingest_activity": INTERPRET_RETRY_POLICY,
    "extract_document_text_activity": INTERPRET_RETRY_POLICY,
}

# Long-running activities that heartbeat between LLM calls, so a hung call is
# detected well before start_to_close_timeout. The heartbeat fires once per
# page BEFORE each vision call; one call can legitimately take ~180s
# (llm_timeout_seconds x (1 + llm_num_retries) inside litellm), so the timeout
# must exceed that worst case or Temporal kills a healthy activity.
_HEARTBEATS: dict[str, timedelta] = {
    "extract_document_text_activity": timedelta(seconds=300),
}


def activity_options(name: str) -> dict:
    """Return execute_activity kwargs (timeout + retry policy) for an activity."""
    options = {
        "start_to_close_timeout": _TIMEOUTS[name],
        "retry_policy": _POLICIES.get(name, DEFAULT_RETRY_POLICY),
    }
    if name in _HEARTBEATS:
        options["heartbeat_timeout"] = _HEARTBEATS[name]
    return options
