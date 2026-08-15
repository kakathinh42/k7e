"""Upload validation utilities.

Provides deterministic validation for file uploads to the wiki platform.
"""

from __future__ import annotations

MAX_UPLOAD_BYTES: int = 5 * 1024 * 1024  # 5 MiB (text/markdown)
#: PDFs and images are larger by nature; they get their own cap.
MAX_UPLOAD_BYTES_EXTRACTABLE: int = 25 * 1024 * 1024  # 25 MiB

#: Binary types that go through vision extraction instead of utf-8 decode.
#: The worker imports this to decide which documents need the extract step.
EXTRACTABLE_MIME: frozenset[str] = frozenset({"application/pdf", "image/png", "image/jpeg"})

ALLOWED_MIME: frozenset[str] = frozenset({"text/plain", "text/markdown"}) | EXTRACTABLE_MIME


def max_upload_bytes_for(mime: str) -> int:
    """Return the size cap for a MIME type (extractable types get 25 MiB)."""
    if mime in EXTRACTABLE_MIME:
        return MAX_UPLOAD_BYTES_EXTRACTABLE
    return MAX_UPLOAD_BYTES


def validate_upload(filename: str, mime: str, size: int) -> None:
    """Validate a file upload against platform constraints.

    Args:
        filename: The name of the file being uploaded. Must be non-empty
                  and not consist solely of whitespace.
        mime: The MIME type of the upload. Must be one of ALLOWED_MIME.
        size: The file size in bytes. Must not exceed the cap for *mime*
            (``MAX_UPLOAD_BYTES`` for text, ``MAX_UPLOAD_BYTES_EXTRACTABLE``
            for PDF/image types).

    Raises:
        ValueError: With message ``"empty filename"`` if *filename* is empty
            or whitespace-only.
        ValueError: With message ``"unsupported mime type"`` if *mime* is not
            in ALLOWED_MIME.
        ValueError: With message ``"file too large"`` if *size* exceeds the
            cap for *mime*.
    """
    if not filename or not filename.strip():
        raise ValueError("empty filename")

    if mime not in ALLOWED_MIME:
        raise ValueError("unsupported mime type")

    if size > max_upload_bytes_for(mime):
        raise ValueError("file too large")
