"""wiki-MCP save_to_wiki ingest tool — ingests text into the caller's personal
space, authenticated by the forwarded credential (PAT SSO T9)."""

from __future__ import annotations

import httpx
import pytest
from k7e_mcp.client import save_to_wiki


@pytest.mark.asyncio
async def test_save_to_wiki_uploads_to_personal_space_with_forwarded_auth():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = request.content
        return httpx.Response(200, json={"raw_document_id": "r1", "workflow_id": "w1"})

    res = await save_to_wiki(
        "the secret plan is BLUEJAY",
        "My Note",
        base="http://x",
        transport=httpx.MockTransport(handler),
        authorization="Bearer wpat_abc",
    )
    assert seen["method"] == "POST"
    assert seen["path"] == "/ingest/upload"
    assert seen["auth"] == "Bearer wpat_abc"  # runs as the PAT owner
    # routed to the caller's personal space + carries the content
    assert b"personal" in seen["body"]
    assert b"the secret plan is BLUEJAY" in seen["body"]
    assert res["raw_document_id"] == "r1"


@pytest.mark.asyncio
async def test_save_to_wiki_sanitizes_a_traversal_title():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        return httpx.Response(200, json={"raw_document_id": "r", "workflow_id": "w"})

    await save_to_wiki(
        "x",
        "../../etc/passwd",
        base="http://x",
        transport=httpx.MockTransport(handler),
        authorization="Bearer wpat_abc",
    )
    # the multipart filename must not carry the traversal (dots/slashes → '-')
    assert b"../" not in seen["body"]
    assert b"etc/passwd" not in seen["body"]


@pytest.mark.asyncio
async def test_save_to_wiki_raises_on_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "forbidden"})

    with pytest.raises(httpx.HTTPStatusError):
        await save_to_wiki(
            "x",
            "t",
            base="http://x",
            transport=httpx.MockTransport(handler),
            authorization="Bearer wpat_abc",
        )
