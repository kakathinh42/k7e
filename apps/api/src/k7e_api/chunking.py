"""Deterministic Markdown chunking for embedding.

Splits on blank-line paragraph boundaries and packs paragraphs up to
``max_chars`` with a small character overlap between consecutive chunks.
Char-based sizing is an intentional MVP approximation of token windows.
"""

from __future__ import annotations


def chunk_markdown(text: str, max_chars: int = 2000, overlap_chars: int = 200) -> list[str]:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        candidate = para if not current else f"{current}\n\n{para}"
        if len(candidate) <= max_chars or not current:
            current = candidate
        else:
            chunks.append(current)
            tail = current[-overlap_chars:] if overlap_chars else ""
            current = f"{tail}\n\n{para}" if tail else para
    if current:
        chunks.append(current)
    return chunks
