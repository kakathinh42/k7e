"""Tests for extract_document_text_activity + load_raw_document binary handling.

Activities are plain async functions — called directly, no Temporal runtime.
The vision LLM is always StubLLMClient; PDFs are generated in-test.
"""

from __future__ import annotations

import io
import uuid

import pypdfium2 as pdfium
import pytest
from k7e_api.llm_client import StubLLMClient
from k7e_api.models import Base, IngestRun, RawDocument
from k7e_worker import activities, extract_activities
from sqlalchemy import StaticPool, create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from temporalio.exceptions import ApplicationError


@pytest.fixture()
def worker_sqlite_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False, class_=Session)
    Base.metadata.drop_all(engine)
    engine.dispose()


def make_pdf(n_pages: int) -> bytes:
    doc = pdfium.PdfDocument.new()
    for _ in range(n_pages):
        doc.new_page(200, 200)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _insert_raw_doc(factory, tmp_path, data: bytes, mime: str) -> str:
    path = tmp_path / "blob.bin"
    path.write_bytes(data)
    with factory() as session:
        doc = RawDocument(
            filename="doc.bin",
            sha256="0" * 64,
            object_store_ref=str(path),
            mime_type=mime,
            size_bytes=len(data),
        )
        session.add(doc)
        session.commit()
        return str(doc.id)


# ---------------------------------------------------------------------------
# load_raw_document: binary vs text handling
# ---------------------------------------------------------------------------


async def test_load_raw_document_flags_pdf_for_extraction(
    monkeypatch, worker_sqlite_factory, tmp_path
):
    monkeypatch.setattr(activities, "session_factory", worker_sqlite_factory)
    doc_id = _insert_raw_doc(worker_sqlite_factory, tmp_path, make_pdf(1), "application/pdf")
    result = await activities.load_raw_document(doc_id)
    assert result["needs_extraction"] is True
    assert result["text"] is None
    assert result["mime"] == "application/pdf"


async def test_load_raw_document_text_path_unchanged(monkeypatch, worker_sqlite_factory, tmp_path):
    monkeypatch.setattr(activities, "session_factory", worker_sqlite_factory)
    doc_id = _insert_raw_doc(worker_sqlite_factory, tmp_path, b"# hello", "text/markdown")
    result = await activities.load_raw_document(doc_id)
    assert result["needs_extraction"] is False
    assert result["text"] == "# hello"


# ---------------------------------------------------------------------------
# extract_document_text_activity
# ---------------------------------------------------------------------------


async def test_extract_activity_transcribes_pdf(monkeypatch, worker_sqlite_factory, tmp_path):
    monkeypatch.setattr(extract_activities, "session_factory", worker_sqlite_factory)
    monkeypatch.setattr(extract_activities, "llm_client_factory", StubLLMClient)
    doc_id = _insert_raw_doc(worker_sqlite_factory, tmp_path, make_pdf(2), "application/pdf")

    result = await extract_activities.extract_document_text_activity(doc_id)

    assert result["page_count"] == 2
    assert result["transcribed_pages"] == 2
    assert result["truncated"] is False
    assert "Stub transcription" in result["text"]
    assert "--- Page 2 of 2 ---" in result["text"]


async def test_extract_activity_records_vision_ingest_run(
    monkeypatch, worker_sqlite_factory, tmp_path
):
    monkeypatch.setattr(extract_activities, "session_factory", worker_sqlite_factory)
    monkeypatch.setattr(extract_activities, "llm_client_factory", StubLLMClient)
    doc_id = _insert_raw_doc(worker_sqlite_factory, tmp_path, make_pdf(2), "application/pdf")

    await extract_activities.extract_document_text_activity(doc_id)

    with worker_sqlite_factory() as session:
        run = session.execute(select(IngestRun)).scalar_one()
        assert run.model_id == "wiki-vision"
        assert run.llm_calls == 2  # one vision call per page
        assert str(run.raw_document_id) == doc_id


async def test_extract_activity_merges_extraction_metadata(
    monkeypatch, worker_sqlite_factory, tmp_path
):
    monkeypatch.setattr(extract_activities, "session_factory", worker_sqlite_factory)
    monkeypatch.setattr(extract_activities, "llm_client_factory", StubLLMClient)
    doc_id = _insert_raw_doc(worker_sqlite_factory, tmp_path, make_pdf(1), "application/pdf")

    await extract_activities.extract_document_text_activity(doc_id)

    with worker_sqlite_factory() as session:
        doc = session.get(RawDocument, uuid.UUID(doc_id))
        extraction = doc.extra_metadata["extraction"]
        assert extraction["transcribed_pages"] == 1
        assert extraction["truncated"] is False
        assert extraction["vision_model"] == "wiki-vision"
        assert extraction["chars"] > 0


async def test_extract_activity_missing_document_non_retryable(monkeypatch, worker_sqlite_factory):
    monkeypatch.setattr(extract_activities, "session_factory", worker_sqlite_factory)
    with pytest.raises(ApplicationError) as ei:
        await extract_activities.extract_document_text_activity(str(uuid.uuid4()))
    assert ei.value.non_retryable is True


async def test_extract_activity_rejects_text_mime_non_retryable(
    monkeypatch, worker_sqlite_factory, tmp_path
):
    """A text document reaching the extract activity is a workflow bug."""
    monkeypatch.setattr(extract_activities, "session_factory", worker_sqlite_factory)
    doc_id = _insert_raw_doc(worker_sqlite_factory, tmp_path, b"# hello", "text/markdown")
    with pytest.raises(ApplicationError) as ei:
        await extract_activities.extract_document_text_activity(doc_id)
    assert ei.value.non_retryable is True


async def test_extract_activity_corrupt_pdf_non_retryable(
    monkeypatch, worker_sqlite_factory, tmp_path
):
    monkeypatch.setattr(extract_activities, "session_factory", worker_sqlite_factory)
    monkeypatch.setattr(extract_activities, "llm_client_factory", StubLLMClient)
    doc_id = _insert_raw_doc(worker_sqlite_factory, tmp_path, b"junk bytes", "application/pdf")
    with pytest.raises(ApplicationError) as ei:
        await extract_activities.extract_document_text_activity(doc_id)
    assert ei.value.non_retryable is True
