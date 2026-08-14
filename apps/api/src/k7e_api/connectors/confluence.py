"""Confluence connector: pull a space's pages as Tier-A documents.

The HTTP client is injected (a ``http_get(url) -> dict`` callable) so the
connector is pure and unit-testable with a fake; the registry builds the real
authed callable from the space's base_url + the API token in settings.
"""

from __future__ import annotations

from typing import Callable, Iterable

from k7e_api.connectors.base import FetchedDocument
from k7e_api.logging_setup import get_logger

logger = get_logger(__name__)


class ConfluenceConnector:
    name = "confluence"

    def __init__(
        self,
        *,
        base_url: str,
        space_key: str,
        http_get: Callable[[str], dict],
        page_limit: int = 50,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._space_key = space_key
        self._http_get = http_get
        self._page_limit = page_limit

    def _first_url(self) -> str:
        return (
            f"{self._base_url}/rest/api/content?spaceKey={self._space_key}"
            f"&expand=body.storage,version&limit={self._page_limit}&start=0"
        )

    def fetch(self) -> Iterable[FetchedDocument]:
        url: str | None = self._first_url()
        while url:
            data = self._http_get(url)
            for page in data.get("results", []):
                doc = self._to_doc(page)
                if doc is not None:
                    yield doc
            nxt = (data.get("_links") or {}).get("next")
            url = f"{self._base_url}{nxt}" if nxt else None

    def _to_doc(self, page: dict) -> FetchedDocument | None:
        try:
            page_id = str(page["id"])
            title = page.get("title") or page_id
            body = ((page.get("body") or {}).get("storage") or {}).get("value") or ""
            return FetchedDocument(
                source_system="confluence",
                source_external_id=page_id,
                source_tier="A",
                filename=f"{title}.html",
                content=body.encode("utf-8"),
                content_type="text/html",
            )
        except Exception as exc:  # noqa: BLE001 - one bad page never aborts the run
            logger.warning("confluence_page_skip", page=page.get("id"), error=str(exc))
            return None
