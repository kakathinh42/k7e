"""wiki-MCP forwards the delegated identity headers to the API."""

from __future__ import annotations

import httpx
import pytest
from k7e_mcp.client import _headers, search_wiki


def test_headers_prefers_delegated_identity():
    h = _headers(app_key="wapp_x", on_behalf_email="alice@example.com")
    assert h["X-App-Key"] == "wapp_x"
    assert h["X-On-Behalf-Of-Email"] == "alice@example.com"
    assert "X-User-Id" not in h  # fixed identity not sent when delegating


def test_headers_falls_back_to_fixed_identity():
    h = _headers()
    assert h["X-User-Id"]  # env fixed identity when nothing forwarded


@pytest.mark.asyncio
async def test_search_wiki_sends_delegated_headers():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, json={"hits": []})

    await search_wiki(
        "q",
        base="http://x",
        transport=httpx.MockTransport(handler),
        app_key="wapp_x",
        on_behalf_email="alice@example.com",
    )
    assert seen["x-app-key"] == "wapp_x"
    assert seen["x-on-behalf-of-email"] == "alice@example.com"
