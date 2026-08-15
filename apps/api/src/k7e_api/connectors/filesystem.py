"""Filesystem connector: ingest a directory of files as Tier-A documents.

The simplest concrete connector — no external credentials. Credentialed
connectors (Confluence, Jira, Zoom, Slack) implement the same Connector protocol.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Iterable

from k7e_api.connectors.base import FetchedDocument


class FilesystemConnector:
    name = "filesystem"

    def __init__(
        self,
        root: str,
        patterns: list[str] | None = None,
        source_tier: str = "A",
    ) -> None:
        self._root = Path(root)
        self._patterns = patterns or ["*.md", "*.txt"]
        self._source_tier = source_tier

    def _matches(self, name: str) -> bool:
        return any(fnmatch.fnmatch(name, p) for p in self._patterns)

    def fetch(self) -> Iterable[FetchedDocument]:
        for path in sorted(self._root.rglob("*")):
            if not path.is_file() or not self._matches(path.name):
                continue
            rel = str(path.relative_to(self._root))
            yield FetchedDocument(
                source_system="filesystem",
                source_external_id=rel,
                source_tier=self._source_tier,
                filename=path.name,
                content=path.read_bytes(),
                content_type="text/markdown",
            )
