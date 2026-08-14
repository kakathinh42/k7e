from datetime import timedelta

from k7e_worker.retry import (
    DEFAULT_RETRY_POLICY,
    INTERPRET_RETRY_POLICY,
    activity_options,
)
from temporalio.common import RetryPolicy


def test_default_policy_attempts():
    assert isinstance(DEFAULT_RETRY_POLICY, RetryPolicy)
    assert DEFAULT_RETRY_POLICY.maximum_attempts == 3


def test_activity_options_for_load():
    opts = activity_options("load_raw_document")
    assert opts["start_to_close_timeout"] == timedelta(seconds=30)
    assert opts["retry_policy"] is DEFAULT_RETRY_POLICY


def test_activity_options_for_okf_ingest_uses_interpret_policy():
    opts = activity_options("okf_ingest_activity")
    assert opts["start_to_close_timeout"] == timedelta(seconds=600)
    assert opts["retry_policy"] is INTERPRET_RETRY_POLICY


def test_activity_options_for_extract_uses_interpret_policy_and_heartbeat():
    """Vision extraction: up to 50 sequential LLM calls — long timeout,
    LLM retry policy, and a heartbeat so a hung call is detected.

    The heartbeat fires once per page, BEFORE each vision call, and a single
    call may legitimately run ~180s (llm_timeout_seconds=60 x 3 litellm
    attempts). The heartbeat timeout must comfortably exceed that or Temporal
    kills a healthy activity and re-pays every page transcription.
    """
    opts = activity_options("extract_document_text_activity")
    assert opts["start_to_close_timeout"] == timedelta(seconds=900)
    assert opts["retry_policy"] is INTERPRET_RETRY_POLICY
    assert opts["heartbeat_timeout"] == timedelta(seconds=300)


def test_activity_options_without_heartbeat_has_no_heartbeat_key():
    assert "heartbeat_timeout" not in activity_options("load_raw_document")
