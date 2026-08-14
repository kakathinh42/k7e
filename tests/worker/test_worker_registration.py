"""Guard: the worker must register every activity its workflows can invoke.

Regression for an upload failing with NotFoundError because an activity the
workflow calls was never registered on the worker.
"""

from __future__ import annotations

from k7e_worker.main import INGEST_ACTIVITIES

# Activities referenced by IngestWorkflow.run (v2 OKF pipeline).
_EXPECTED = {
    "load_raw_document",
    "extract_document_text_activity",
    "redact_activity",
    "okf_ingest_activity",
    "okf_mirror_activity",
    "embed_backfill_activity",
}


def _names(activities) -> set[str]:
    out = set()
    for a in activities:
        # @activity.defn preserves __name__; fall back to the wrapped fn.
        out.add(getattr(a, "__name__", None) or getattr(getattr(a, "fn", None), "__name__", ""))
    return out


def test_worker_registers_all_workflow_activities():
    registered = _names(INGEST_ACTIVITIES)
    missing = _EXPECTED - registered
    assert not missing, f"worker is missing activities: {missing}"


def test_okf_activities_are_registered():
    # The v2 ingest path — keep an explicit canary.
    names = _names(INGEST_ACTIVITIES)
    assert "okf_ingest_activity" in names
    assert "okf_mirror_activity" in names
