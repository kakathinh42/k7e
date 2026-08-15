"""Tests for k7e_api.validation module.

TDD: these tests are written before the module is implemented.
"""

import pytest
from k7e_api.validation import (
    ALLOWED_MIME,
    EXTRACTABLE_MIME,
    MAX_UPLOAD_BYTES,
    MAX_UPLOAD_BYTES_EXTRACTABLE,
    validate_upload,
)


class TestValidateUploadEmptyFilename:
    """Test that empty or whitespace-only filenames are rejected."""

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="empty filename"):
            validate_upload("", "text/plain", 100)

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="empty filename"):
            validate_upload("   ", "text/plain", 100)

    def test_tab_only_raises(self):
        with pytest.raises(ValueError, match="empty filename"):
            validate_upload("\t", "text/plain", 100)


class TestValidateUploadUnsupportedMime:
    """Test that MIME types not in ALLOWED_MIME are rejected."""

    def test_application_octet_stream_raises(self):
        with pytest.raises(ValueError, match="unsupported mime type"):
            validate_upload("file.bin", "application/octet-stream", 100)

    def test_text_html_raises(self):
        with pytest.raises(ValueError, match="unsupported mime type"):
            validate_upload("page.html", "text/html", 100)


class TestValidateUploadFileSize:
    """Test that files exceeding the max upload size are rejected."""

    def test_exactly_max_passes(self):
        # Exactly at the limit should NOT raise (boundary: allowed)
        validate_upload("doc.md", "text/markdown", MAX_UPLOAD_BYTES)

    def test_one_byte_over_raises(self):
        with pytest.raises(ValueError, match="file too large"):
            validate_upload("doc.md", "text/markdown", MAX_UPLOAD_BYTES + 1)

    def test_way_over_raises(self):
        with pytest.raises(ValueError, match="file too large"):
            validate_upload("big.md", "text/markdown", MAX_UPLOAD_BYTES * 2)


class TestValidateUploadConstants:
    """Test that exported constants have correct values."""

    def test_max_upload_bytes_is_5mib(self):
        assert MAX_UPLOAD_BYTES == 5 * 1024 * 1024

    def test_allowed_mime_contains_text_plain(self):
        assert "text/plain" in ALLOWED_MIME

    def test_allowed_mime_contains_text_markdown(self):
        assert "text/markdown" in ALLOWED_MIME

    def test_allowed_mime_contains_extractable_types(self):
        assert "application/pdf" in ALLOWED_MIME
        assert "image/png" in ALLOWED_MIME
        assert "image/jpeg" in ALLOWED_MIME
        assert EXTRACTABLE_MIME <= ALLOWED_MIME

    def test_extractable_cap_is_25mib(self):
        assert MAX_UPLOAD_BYTES_EXTRACTABLE == 25 * 1024 * 1024


class TestValidateUploadExtractableTypes:
    """PDF/image uploads are accepted with their own (larger) size cap."""

    def test_pdf_accepted(self):
        validate_upload("doc.pdf", "application/pdf", 100)

    def test_png_accepted(self):
        validate_upload("shot.png", "image/png", 100)

    def test_jpeg_accepted(self):
        validate_upload("photo.jpg", "image/jpeg", 100)

    def test_pdf_exactly_extractable_cap_passes(self):
        validate_upload("doc.pdf", "application/pdf", MAX_UPLOAD_BYTES_EXTRACTABLE)

    def test_pdf_over_extractable_cap_raises(self):
        with pytest.raises(ValueError, match="file too large"):
            validate_upload("doc.pdf", "application/pdf", MAX_UPLOAD_BYTES_EXTRACTABLE + 1)

    def test_text_does_not_get_extractable_cap(self):
        """Text files keep the original 5 MiB cap."""
        with pytest.raises(ValueError, match="file too large"):
            validate_upload("doc.md", "text/markdown", MAX_UPLOAD_BYTES + 1)


class TestValidateUploadValidCases:
    """Test valid upload scenarios that must not raise."""

    def test_valid_markdown_upload(self):
        """A typical markdown file upload must not raise."""
        validate_upload("doc.md", "text/markdown", 1024)

    def test_valid_plain_text_upload(self):
        """A plain text file upload must not raise."""
        validate_upload("readme.txt", "text/plain", 512)

    def test_valid_markdown_zero_size(self):
        """Zero-byte file is allowed (empty document)."""
        validate_upload("empty.md", "text/markdown", 0)

    def test_filename_with_path_separators(self):
        """Filenames with path separators are not empty, should pass if mime/size ok."""
        validate_upload("path/to/doc.md", "text/markdown", 100)
