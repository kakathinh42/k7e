"""Vision extraction of PDF/image uploads into plain text.

Pure module (no DB, no Temporal): rasterizes PDF pages with pypdfium2, sends
each page / image to a vision LLM via ``LLMClient.transcribe_image``, and
joins the per-page transcripts. Mirrors the layout of ``redaction.py`` so the
upload endpoint (page-count precheck) and the worker activity can both reuse
it. Raw bytes are passed in by the caller — nothing here reads the object
store.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass

import pypdfium2 as pdfium

from k7e_api.llm_client import LLMClient

#: Render scale for PDF pages (~150 DPI: text-legible, modest payload).
RENDER_SCALE = 150 / 72
JPEG_QUALITY = 85
#: Images larger than this (bytes or pixels on the longest side) are
#: re-encoded to JPEG so the base64 request body stays gateway-friendly.
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_IMAGE_DIMENSION = 2500

PAGE_MARKER = "\n\n--- Page {n} of {total} ---\n\n"
TRUNCATION_NOTE = "\n\n[Note: document truncated — transcribed {n} of {total} pages.]\n"

VISION_SYSTEM_PROMPT = (
    "You transcribe documents faithfully into GitHub-flavored Markdown. "
    "Reproduce all visible text verbatim. Render tables as Markdown tables. "
    "Describe diagrams, charts, and figures in brackets, e.g. "
    "[Figure: architecture diagram showing ...]. Do not add commentary or "
    "headers of your own. If the page is blank, return nothing."
)

VISION_PDF_PAGE_PROMPT = "Transcribe page {n} of {total} of this document."
VISION_IMAGE_PROMPT = (
    "Transcribe this image. If it is a screenshot or diagram, describe its "
    "structure and reproduce any visible text."
)

PDF_MIME = "application/pdf"
IMAGE_MIMES = frozenset({"image/png", "image/jpeg"})


class ExtractionError(Exception):
    """Raised for unreadable input or an unusable (empty) transcription."""


@dataclass(frozen=True)
class ExtractionResult:
    text: str
    page_count: int  # true page count of the source (1 for images)
    transcribed_pages: int
    truncated: bool


def pdf_page_count(data: bytes) -> int:
    """Return the number of pages in a PDF, raising ``ExtractionError`` if unreadable."""
    try:
        doc = pdfium.PdfDocument(data)
    except Exception as exc:
        raise ExtractionError(f"unreadable pdf: {exc}") from exc
    try:
        return len(doc)
    finally:
        doc.close()


def rasterize_pdf(data: bytes, *, max_pages: int, scale: float = RENDER_SCALE) -> list[bytes]:
    """Render up to ``max_pages`` PDF pages to JPEG bytes."""
    try:
        doc = pdfium.PdfDocument(data)
    except Exception as exc:
        raise ExtractionError(f"unreadable pdf: {exc}") from exc
    images: list[bytes] = []
    try:
        for index in range(min(len(doc), max_pages)):
            page = doc[index]
            try:
                bitmap = page.render(scale=scale)
                images.append(_encode_jpeg(bitmap.to_pil()))
            finally:
                page.close()
    finally:
        doc.close()
    return images


async def extract_text(
    data: bytes,
    mime: str,
    *,
    client: LLMClient,
    max_pdf_pages: int,
    on_page: Callable[[int], None] | None = None,
) -> ExtractionResult:
    """Transcribe a PDF or image into plain text via the vision LLM.

    ``on_page`` is invoked with the 1-based page number before each vision
    call (heartbeat seam for the Temporal activity).

    Raises:
        ExtractionError: Unsupported mime, unreadable input, or a fully
            empty transcription.
    """
    if mime == PDF_MIME:
        return await _extract_pdf(data, client=client, max_pages=max_pdf_pages, on_page=on_page)
    if mime in IMAGE_MIMES:
        return await _extract_image(data, mime, client=client, on_page=on_page)
    raise ExtractionError(f"unsupported mime type for extraction: {mime}")


async def _extract_pdf(
    data: bytes,
    *,
    client: LLMClient,
    max_pages: int,
    on_page: Callable[[int], None] | None,
) -> ExtractionResult:
    total = pdf_page_count(data)
    if total == 0:
        raise ExtractionError("pdf has no pages")
    pages = rasterize_pdf(data, max_pages=max_pages)
    transcripts: list[str] = []
    for n, jpeg in enumerate(pages, start=1):
        if on_page is not None:
            on_page(n)
        transcripts.append(
            await client.transcribe_image(
                system=VISION_SYSTEM_PROMPT,
                user=VISION_PDF_PAGE_PROMPT.format(n=n, total=total),
                image_mime="image/jpeg",
                image_data=jpeg,
            )
        )
    parts: list[str] = []
    for n, transcript in enumerate(transcripts, start=1):
        if not transcript.strip():
            continue  # blank page
        if parts:
            parts.append(PAGE_MARKER.format(n=n, total=total))
        parts.append(transcript.strip())
    if not parts:
        raise ExtractionError("no text could be extracted from the pdf")
    truncated = len(pages) < total
    text = "".join(parts)
    if truncated:
        text += TRUNCATION_NOTE.format(n=len(pages), total=total)
    return ExtractionResult(
        text=text,
        page_count=total,
        transcribed_pages=len(pages),
        truncated=truncated,
    )


async def _extract_image(
    data: bytes,
    mime: str,
    *,
    client: LLMClient,
    on_page: Callable[[int], None] | None,
) -> ExtractionResult:
    data, mime = _normalize_image(data, mime)
    if on_page is not None:
        on_page(1)
    transcript = await client.transcribe_image(
        system=VISION_SYSTEM_PROMPT,
        user=VISION_IMAGE_PROMPT,
        image_mime=mime,
        image_data=data,
    )
    if not transcript.strip():
        raise ExtractionError("no text could be extracted from the image")
    return ExtractionResult(
        text=transcript.strip(), page_count=1, transcribed_pages=1, truncated=False
    )


def _normalize_image(data: bytes, mime: str) -> tuple[bytes, str]:
    """Re-encode oversized images to a bounded JPEG; small ones pass through.

    A 25 MiB PNG would become a ~33 MB base64 request body — larger than
    gateways typically accept — so anything above ``MAX_IMAGE_BYTES`` or
    ``MAX_IMAGE_DIMENSION`` is downscaled/re-encoded. Unreadable image bytes
    raise ``ExtractionError``.
    """
    from PIL import Image

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:
        raise ExtractionError(f"unreadable image: {exc}") from exc
    if len(data) <= MAX_IMAGE_BYTES and max(image.size) <= MAX_IMAGE_DIMENSION:
        return data, mime
    image.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION))
    return _encode_jpeg(image), "image/jpeg"


def _encode_jpeg(image) -> bytes:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()
