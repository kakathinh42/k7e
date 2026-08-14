"""wiki-MCP forwards a wpat_ PAT (as Authorization) to the API (PAT SSO T8)."""

from __future__ import annotations

import httpx
import pytest
from k7e_mcp.client import _headers, search_wiki


def test_headers_forwards_pat_bearer_when_no_delegation():
    h = _headers("Bearer wpat_abc")
    assert h == {"Authorization": "Bearer wpat_abc"}
    assert "X-User-Id" not in h  # a real credential → not the fixed identity


def test_delegation_still_wins_over_a_bearer():
    # if both are present the delegated pair wins (unchanged priority)
    h = _headers("Bearer wpat_abc", app_key="wapp_x", on_behalf_email="a@example.com")
    assert "X-App-Key" in h and "Authorization" not in h


@pytest.mark.asyncio
async def test_search_wiki_forwards_pat_bearer():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"hits": []})

    await search_wiki(
        "q",
        base="http://x",
        transport=httpx.MockTransport(handler),
        authorization="Bearer wpat_abc",
    )
    assert seen["auth"] == "Bearer wpat_abc"
