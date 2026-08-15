"""Connector abstraction: pull external sources into FetchedDocuments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol, runtime_checkable


@dataclass
class FetchedDocument:
    """A document pulled from an external source, ready to ingest."""

    source_system: str
    source_external_id: str
    source_tier: str  # 'A' authoritative/page-like | 'B' conversational
    filename: str
    content: bytes
    content_type: str = "text/markdown"
    extra_metadata: dict | None = None


@runtime_checkable
class Connector(Protocol):
    """A source connector yields FetchedDocuments to ingest."""

    name: str

    def fetch(self) -> Iterable[FetchedDocument]:
        """Yield documents from the external source."""
        ...
