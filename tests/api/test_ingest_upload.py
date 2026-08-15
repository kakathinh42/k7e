"""Tests for POST /ingest/upload endpoint (Task 3.2).

TDD: tests written before implementation to drive the design.

Uses an in-memory SQLite database with a shared connection pool so that
the schema created by ``Base.metadata.create_all`` is visible to all
subsequent sessions in the same test.  All external dependencies are
overridden:

- ``k7e_api.db.get_session``   -> SQLite session (via StaticPool)
- ``get_object_store``          -> LocalFileObjectStore(tmp_path)
- ``get_workflow_starter``      -> fake recorder returning "wf-test-123"
"""

from __future__ import annotations

import hashlib
import uuid

import k7e_api.db as db_module
import pytest
from fastapi.testclient import TestClient
from k7e_api.deps import get_object_store, get_workflow_starter
from k7e_api.main import app
from k7e_api.models import Base, RawDocument
from k7e_api.object_store import LocalFileObjectStore
from k7e_api.tenancy import get_tenant_context
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

from tests.api.conftest import TEST_TENANT_CONTEXT

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sqlite_engine():
    """Create an in-memory SQLite engine with a StaticPool.

    StaticPool ensures all connections share the same in-memory database,
    so tables created by ``create_all`` are visible inside FastAPI handler
    sessions.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def sqlite_session_factory(sqlite_engine):
    """Return a sessionmaker bound to the shared SQLite engine."""
    return sessionmaker(sqlite_engine, expire_on_commit=False, class_=Session)


@pytest.fixture()
def started_workflow_ids():
    """Mutable list that the fake workflow starter appends to."""
    return []


@pytest.fixture()
def client(tmp_path, sqlite_session_factory, started_workflow_ids):
    """Return a TestClient with all external deps overridden."""

    def override_get_session():
        session = sqlite_session_factory()
        try:
            yield session
        finally:
            session.close()

    def override_get_object_store():
        return LocalFileObjectStore(str(tmp_path))

    def override_get_workflow_starter():
        def fake_starter(raw_document_id: str) -> str:
            started_workflow_ids.append(raw_document_id)
            return "wf-test-123"

        return fake_starter

    app.dependency_overrides[db_module.get_session] = override_get_session
    app.dependency_overrides[get_object_store] = override_get_object_store
    app.dependency_overrides[get_workflow_starter] = override_get_workflow_starter
    app.dependency_overrides[get_tenant_context] = lambda: TEST_TENANT_CONTEXT

    yield TestClient(app)

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestUploadCreatesRawDocumentAndStartsWorkflow:
    """POST /ingest/upload with a valid markdown file."""

    def test_returns_200_with_workflow_id_and_raw_document_id(
        self, client, sqlite_session_factory
    ):
        file_content = b"# Title\nhello"
        response = client.post(
            "/ingest/upload",
            files={"file": ("doc.md", file_content, "text/markdown")},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["workflow_id"] == "wf-test-123"
        # raw_document_id must be a valid UUID string
        raw_doc_id = body["raw_document_id"]
        assert uuid.UUID(str(raw_doc_id))  # raises ValueError if invalid

    def test_raw_document_row_created_with_correct_sha256(self, client, sqlite_session_factory):
        file_content = b"# Title\nhello"
        response = client.post(
            "/ingest/upload",
            files={"file": ("doc.md", file_content, "text/markdown")},
        )
        assert response.status_code == 200, response.text
        raw_doc_id = response.json()["raw_document_id"]

        expected_sha256 = hashlib.sha256(file_content).hexdigest()

        session = sqlite_session_factory()
        try:
            row = session.get(RawDocument, uuid.UUID(str(raw_doc_id)))
            assert row is not None, "RawDocument row not found in DB"
            assert row.sha256 == expected_sha256, (
                f"sha256 mismatch: got {row.sha256!r}, want {expected_sha256!r}"
            )
            assert row.filename == "doc.md"
            assert row.mime_type == "text/markdown"
            assert row.size_bytes == len(file_content)
            assert row.status == "received"
        finally:
            session.close()

    def test_workflow_starter_called_with_raw_document_id(self, client, started_workflow_ids):
        file_content = b"# Title\nhello"
        response = client.post(
            "/ingest/upload",
            files={"file": ("doc.md", file_content, "text/markdown")},
        )
        assert response.status_code == 200, response.text
        raw_doc_id = response.json()["raw_document_id"]
        # The fake starter should have been called exactly once
        assert len(started_workflow_ids) == 1
        assert started_workflow_ids[0] == str(raw_doc_id)


class TestUploadPdfAndImage:
    """POST /ingest/upload with PDF/image files (vision-extraction types)."""

    @staticmethod
    def _make_pdf(n_pages: int) -> bytes:
        import io

        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument.new()
        for _ in range(n_pages):
            doc.new_page(200, 200)
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()

    def test_pdf_upload_accepted_with_page_count_metadata(
        self, client, sqlite_session_factory, started_workflow_ids
    ):
        response = client.post(
            "/ingest/upload",
            files={"file": ("spec.pdf", self._make_pdf(2), "application/pdf")},
        )
        assert response.status_code == 200, response.text
        raw_doc_id = response.json()["raw_document_id"]
        assert len(started_workflow_ids) == 1

        session = sqlite_session_factory()
        try:
            row = session.get(RawDocument, uuid.UUID(str(raw_doc_id)))
            assert row.mime_type == "application/pdf"
            assert row.extra_metadata == {"page_count": 2}
        finally:
            session.close()

    def test_png_upload_accepted_without_page_count(self, client, sqlite_session_factory):
        import io

        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (16, 16)).save(buf, format="PNG")
        response = client.post(
            "/ingest/upload",
            files={"file": ("shot.png", buf.getvalue(), "image/png")},
        )
        assert response.status_code == 200, response.text
        session = sqlite_session_factory()
        try:
            row = session.get(RawDocument, uuid.UUID(str(response.json()["raw_document_id"])))
            assert row.mime_type == "image/png"
            assert row.extra_metadata is None
        finally:
            session.close()

    def test_pdf_over_page_cap_rejected(self, client, monkeypatch):
        from k7e_api.config import get_settings

        monkeypatch.setenv("MAX_PDF_PAGES", "3")
        get_settings.cache_clear()
        try:
            response = client.post(
                "/ingest/upload",
                files={"file": ("big.pdf", self._make_pdf(4), "application/pdf")},
            )
        finally:
            get_settings.cache_clear()
        assert response.status_code == 400, response.text
        assert "pages" in response.json()["detail"]

    def test_corrupt_pdf_rejected(self, client, started_workflow_ids):
        response = client.post(
            "/ingest/upload",
            files={"file": ("bad.pdf", b"not a pdf at all", "application/pdf")},
        )
        assert response.status_code == 400, response.text
        assert "unreadable pdf" in response.json()["detail"]
        assert started_workflow_ids == []


class TestUploadValidation:
    """POST /ingest/upload with invalid inputs returns HTTP 400."""

    def test_upload_rejects_bad_mime(self, client):
        """Uploading with an unsupported MIME type must return 400."""
        response = client.post(
            "/ingest/upload",
            files={"file": ("page.html", b"<html></html>", "text/html")},
        )
        assert response.status_code == 400, response.text
        assert "unsupported mime type" in response.json()["detail"]

    def test_upload_rejects_empty_filename(self, client):
        """Uploading with an explicitly empty filename header must return 400.

        We pass ``filename=None`` via a raw multipart tuple so FastAPI receives
        the file with ``file.filename == ""``.
        """
        # Build the request directly with an unnamed file part
        response = client.post(
            "/ingest/upload",
            content=(
                b"--boundary\r\n"
                b'Content-Disposition: form-data; name="file"\r\n'
                b"Content-Type: text/plain\r\n"
                b"\r\n"
                b"data\r\n"
                b"--boundary--\r\n"
            ),
            headers={"Content-Type": "multipart/form-data; boundary=boundary"},
        )
        # FastAPI either rejects with 422 (missing filename field) or 400
        # depending on how the file field is parsed.  Both are acceptable
        # error responses; the important assertion is that 200 is NOT returned.
        assert response.status_code in (400, 422), response.text


def test_upload_persists_source_identity(client, sqlite_session_factory):
    """source_system/source_external_id form fields are persisted on RawDocument."""
    resp = client.post(
        "/ingest/upload",
        files={"file": ("doc.md", b"# Hello", "text/markdown")},
        data={"source_system": "confluence", "source_external_id": "PAGE-42"},
    )
    assert resp.status_code == 200, resp.text
    rid = resp.json()["raw_document_id"]
    with sqlite_session_factory() as s:
        rd = s.get(RawDocument, uuid.UUID(str(rid)))
        assert rd.source_system == "confluence"
        assert rd.source_external_id == "PAGE-42"


def test_upload_without_external_id_falls_back_to_content_hash(client, sqlite_session_factory):
    """Manual uploads with no external id get the content sha256 as identity.

    This is what lets a re-upload of the same bytes resolve to the same page
    (Tier-A dedup) and be routed to review instead of publishing a duplicate.
    """
    content = b"# Card apply workflow\nstep one"
    expected_sha = hashlib.sha256(content).hexdigest()
    resp = client.post(
        "/ingest/upload",
        files={"file": ("doc.md", content, "text/markdown")},
        # no source_external_id supplied
    )
    assert resp.status_code == 200, resp.text
    rid = resp.json()["raw_document_id"]
    with sqlite_session_factory() as s:
        rd = s.get(RawDocument, uuid.UUID(str(rid)))
        assert rd.source_external_id == expected_sha
        assert rd.source_external_id == rd.sha256


def test_upload_explicit_external_id_overrides_content_hash(client, sqlite_session_factory):
    """An explicit source_external_id is never overwritten by the hash fallback."""
    resp = client.post(
        "/ingest/upload",
        files={"file": ("doc.md", b"# Hello", "text/markdown")},
        data={"source_system": "confluence", "source_external_id": "PAGE-42"},
    )
    assert resp.status_code == 200, resp.text
    rid = resp.json()["raw_document_id"]
    with sqlite_session_factory() as s:
        rd = s.get(RawDocument, uuid.UUID(str(rid)))
        assert rd.source_external_id == "PAGE-42"


def test_upload_explicit_tier_b_is_persisted(client, sqlite_session_factory):
    resp = client.post(
        "/ingest/upload",
        files={"file": ("call.txt", b"Alice: we picked Temporal.", "text/plain")},
        data={"source_system": "manual_upload", "source_tier": "B"},
    )
    assert resp.status_code == 200, resp.text
    rid = resp.json()["raw_document_id"]
    with sqlite_session_factory() as s:
        rd = s.get(RawDocument, uuid.UUID(str(rid)))
        assert rd.source_tier == "B"


def test_upload_tier_defaults_from_source_system(client, sqlite_session_factory):
    resp = client.post(
        "/ingest/upload",
        files={"file": ("notes.md", b"# notes", "text/markdown")},
        data={"source_system": "zoom"},  # no explicit tier -> default B
    )
    assert resp.status_code == 200, resp.text
    rid = resp.json()["raw_document_id"]
    with sqlite_session_factory() as s:
        rd = s.get(RawDocument, uuid.UUID(str(rid)))
        assert rd.source_tier == "B"


def test_upload_invalid_tier_is_rejected(client, sqlite_session_factory):
    resp = client.post(
        "/ingest/upload",
        files={"file": ("a.md", b"# a", "text/markdown")},
        data={"source_tier": "C"},
    )
    assert resp.status_code == 400


def test_upload_allowed_groups_is_parsed_and_persisted(client, sqlite_session_factory):
    """The allowed_groups form field is split on commas (trimmed) onto RawDocument."""
    resp = client.post(
        "/ingest/upload",
        files={"file": ("doc.md", b"# secret", "text/markdown")},
        data={"allowed_groups": "finance, eng"},
    )
    assert resp.status_code == 200, resp.text
    rid = resp.json()["raw_document_id"]
    with sqlite_session_factory() as s:
        rd = s.get(RawDocument, uuid.UUID(str(rid)))
        assert rd.allowed_groups == ["finance", "eng"]


def test_upload_without_allowed_groups_is_public(client, sqlite_session_factory):
    """Omitting allowed_groups leaves RawDocument.allowed_groups null (public)."""
    resp = client.post(
        "/ingest/upload",
        files={"file": ("doc.md", b"# open", "text/markdown")},
    )
    assert resp.status_code == 200, resp.text
    rid = resp.json()["raw_document_id"]
    with sqlite_session_factory() as s:
        rd = s.get(RawDocument, uuid.UUID(str(rid)))
        assert rd.allowed_groups is None
