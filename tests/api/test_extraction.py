"""Tests for k7e_api.extraction — vision extraction of PDF/image uploads.

PDF fixtures are generated in-test with pypdfium2 (no binary files in the
repo). The LLM is always a stub/fake; no network.
"""

import io

import pypdfium2 as pdfium
import pytest
from k7e_api.extraction import (
    ExtractionError,
    extract_text,
    pdf_page_count,
    rasterize_pdf,
)
from k7e_api.llm_client import StubLLMClient


def make_pdf(n_pages: int) -> bytes:
    doc = pdfium.PdfDocument.new()
    for _ in range(n_pages):
        doc.new_page(200, 200)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def make_png(size: tuple[int, int] = (32, 32)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color=(200, 10, 10)).save(buf, format="PNG")
    return buf.getvalue()


class RecordingClient:
    """Fake LLM client that records transcribe_image calls."""

    def __init__(self, replies: list[str] | None = None):
        self.calls: list[dict] = []
        self.replies = replies

    async def transcribe_image(
        self, *, system: str, user: str, image_mime: str, image_data: bytes
    ) -> str:
        self.calls.append({"user": user, "image_mime": image_mime, "image_data": image_data})
        if self.replies is None:
            return f"transcript {len(self.calls)}"
        return self.replies[len(self.calls) - 1]


# ---------------------------------------------------------------------------
# pdf_page_count
# ---------------------------------------------------------------------------


def test_pdf_page_count_counts_pages():
    assert pdf_page_count(make_pdf(1)) == 1
    assert pdf_page_count(make_pdf(3)) == 3


def test_pdf_page_count_rejects_garbage():
    with pytest.raises(ExtractionError):
        pdf_page_count(b"not a pdf")


# ---------------------------------------------------------------------------
# rasterize_pdf
# ---------------------------------------------------------------------------


def test_rasterize_pdf_returns_one_jpeg_per_page():
    images = rasterize_pdf(make_pdf(3), max_pages=10)
    assert len(images) == 3
    for img in images:
        assert img[:2] == b"\xff\xd8"  # JPEG magic


def test_rasterize_pdf_honors_max_pages():
    images = rasterize_pdf(make_pdf(5), max_pages=2)
    assert len(images) == 2


def test_rasterize_pdf_rejects_garbage():
    with pytest.raises(ExtractionError):
        rasterize_pdf(b"junk", max_pages=10)


# ---------------------------------------------------------------------------
# extract_text — PDF path
# ---------------------------------------------------------------------------


async def test_extract_text_pdf_joins_pages_with_markers():
    client = RecordingClient()
    result = await extract_text(make_pdf(3), "application/pdf", client=client, max_pdf_pages=10)
    assert result.page_count == 3
    assert result.transcribed_pages == 3
    assert result.truncated is False
    assert "transcript 1" in result.text
    assert "--- Page 2 of 3 ---" in result.text
    assert "transcript 3" in result.text
    # Per-page prompts tell the model where it is in the document.
    assert "page 1 of 3" in client.calls[0]["user"].lower()
    assert client.calls[1]["image_mime"] == "image/jpeg"


async def test_extract_text_pdf_truncates_beyond_cap_with_note():
    client = RecordingClient()
    result = await extract_text(make_pdf(4), "application/pdf", client=client, max_pdf_pages=2)
    assert result.page_count == 4
    assert result.transcribed_pages == 2
    assert result.truncated is True
    assert len(client.calls) == 2
    assert "truncated" in result.text.lower()
    assert "2 of 4" in result.text


async def test_extract_text_pdf_skips_blank_pages_in_output():
    client = RecordingClient(replies=["only page with text", "", "   "])
    result = await extract_text(make_pdf(3), "application/pdf", client=client, max_pdf_pages=10)
    assert "only page with text" in result.text
    assert result.transcribed_pages == 3


async def test_extract_text_pdf_all_blank_raises():
    client = RecordingClient(replies=["", "", ""])
    with pytest.raises(ExtractionError):
        await extract_text(make_pdf(3), "application/pdf", client=client, max_pdf_pages=10)


async def test_extract_text_pdf_on_page_callback_fires_per_page():
    seen = []
    client = RecordingClient()
    await extract_text(
        make_pdf(2),
        "application/pdf",
        client=client,
        max_pdf_pages=10,
        on_page=seen.append,
    )
    assert seen == [1, 2]


# ---------------------------------------------------------------------------
# extract_text — image path
# ---------------------------------------------------------------------------


async def test_extract_text_image_single_call_original_bytes():
    png = make_png()
    client = RecordingClient(replies=["a red square screenshot"])
    result = await extract_text(png, "image/png", client=client, max_pdf_pages=10)
    assert result.text == "a red square screenshot"
    assert result.page_count == 1
    assert result.transcribed_pages == 1
    assert result.truncated is False
    assert "--- Page" not in result.text
    assert client.calls[0]["image_data"] == png
    assert client.calls[0]["image_mime"] == "image/png"


async def test_extract_text_image_empty_transcript_raises():
    client = RecordingClient(replies=[""])
    with pytest.raises(ExtractionError):
        await extract_text(make_png(), "image/png", client=client, max_pdf_pages=10)


async def test_extract_text_oversized_image_is_normalized_to_jpeg():
    """Very large images are re-encoded (JPEG) so the base64 payload stays sane."""
    from PIL import Image

    big = make_png(size=(3000, 3000))
    client = RecordingClient(replies=["big image"])
    await extract_text(big, "image/png", client=client, max_pdf_pages=10)
    call = client.calls[0]
    assert call["image_mime"] == "image/jpeg"
    assert call["image_data"][:2] == b"\xff\xd8"
    sent = Image.open(io.BytesIO(call["image_data"]))
    assert max(sent.size) <= 2500


async def test_extract_text_unsupported_mime_raises():
    with pytest.raises(ExtractionError):
        await extract_text(b"bytes", "application/zip", client=StubLLMClient(), max_pdf_pages=10)


async def test_extract_text_works_with_stub_llm_client():
    """StubLLMClient satisfies the client interface end-to-end."""
    result = await extract_text(
        make_pdf(1), "application/pdf", client=StubLLMClient(), max_pdf_pages=10
    )
    assert "Stub transcription" in result.text
