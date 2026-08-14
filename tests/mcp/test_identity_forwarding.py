"""M7 Piece 2: the MCP client relays Authorization instead of the env identity."""

from __future__ import annotations

import httpx
from k7e_mcp.client import get_wiki_page, search_wiki


def _capture():
    """A stub transport that records the request headers and returns canned JSON."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = request.headers
        if request.url.path == "/search":
            return httpx.Response(200, json={"hits": []})
        return httpx.Response(200, json={"slug": "s", "title": "T", "markdown_body": "b"})

    return httpx.MockTransport(handler), seen


async def test_authorization_forwarded_instead_of_user_headers():
    transport, seen = _capture()
    await search_wiki("q", transport=transport, authorization="Bearer abc.def.ghi")
    assert seen["headers"]["authorization"] == "Bearer abc.def.ghi"
    assert "x-user-id" not in seen["headers"]


async def test_env_identity_when_no_authorization(monkeypatch):
    monkeypatch.delenv("WIKI_USER_ID", raising=False)
    transport, seen = _capture()
    await get_wiki_page("s", transport=transport)
    assert seen["headers"]["x-user-id"] == "chat-agent"
    assert "authorization" not in seen["headers"]
