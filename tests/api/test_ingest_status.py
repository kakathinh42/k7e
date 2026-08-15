"""GET /ingest/status/{id} derives status (the pipeline never writes it back)."""

from __future__ import annotations

import uuid

from k7e_api.models import IngestRun, RawDocument


def _raw(session, *, status: str = "received") -> uuid.UUID:
    rid = uuid.uuid4()
    session.add(
        RawDocument(
            id=rid,
            filename="doc.md",
            sha256="a" * 64,
            object_store_ref="raw/a",
            mime_type="text/markdown",
            size_bytes=10,
            source_system="manual_upload",
            source_external_id="ext",
            status=status,
            workflow_id=f"ingest-{rid}",
        )
    )
    session.commit()
    return rid


def test_status_processing_while_no_ingest_run(api_client, sqlite_factory):
    with sqlite_factory() as s:
        rid = _raw(s)
    body = api_client.get(f"/ingest/status/{rid}").json()
    assert body["status"] == "processing"
    assert body["workflow_id"] == f"ingest-{rid}"


def test_status_done_once_an_ingest_run_exists(api_client, sqlite_factory):
    with sqlite_factory() as s:
        rid = _raw(s)
        s.add(
            IngestRun(
                raw_document_id=rid,
                filename="doc.md",
                source_slug="doc",
                model_id="wiki-default",
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                llm_calls=1,
                cost_usd=0.001,
                page_count=3,
            )
        )
        s.commit()
    body = api_client.get(f"/ingest/status/{rid}").json()
    assert body["status"] == "done"


def test_status_failed_when_row_marked_failed(api_client, sqlite_factory):
    with sqlite_factory() as s:
        rid = _raw(s, status="failed")
    body = api_client.get(f"/ingest/status/{rid}").json()
    assert body["status"] == "failed"


def test_status_unknown_document_404(api_client):
    resp = api_client.get(f"/ingest/status/{uuid.uuid4()}")
    assert resp.status_code == 404
