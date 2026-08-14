"""Tests for the k7e MCP client shim (HTTP wrapping + result shaping)."""

from __future__ import annotations

import httpx
from k7e_mcp.client import get_wiki_page, list_spaces, search_wiki


async def test_search_wiki_forwards_identity_and_shapes_hits():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search"
        assert request.url.params.get("q") == "payments"
        # permission-aware: identity headers are forwarded
        assert request.headers.get("X-User-Id")
        assert request.headers.get("X-User-Roles")
        return httpx.Response(
            200,
            json={
                "hits": [
                    {
                        "id": "1",
                        "slug": "pay",
                        "title": "Payments",
                        "snippet": "s1",
                        "score": 0.9,
                    },
                    {
                        "id": "2",
                        "slug": "ord",
                        "title": "Orders",
                        "snippet": "s2",
                        "score": 0.5,
                    },
                ]
            },
        )

    hits = await search_wiki(
        "payments", limit=1, base="http://wiki", transport=httpx.MockTransport(handler)
    )
    assert hits == [{"slug": "pay", "title": "Payments", "snippet": "s1", "score": 0.9}]


async def test_get_wiki_page_returns_compiled_markdown():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/items/pay"
        return httpx.Response(
            200,
            json={
                "id": "1",
                "slug": "pay",
                "title": "Payments",
                "status": "published",
                "updated_at": "2026-01-01T00:00:00Z",
                "markdown_body": "# Payments\n\nbody",
                "version": 2,
                "citations": [],
                "model_id": "wiki-default",
            },
        )

    page = await get_wiki_page("pay", base="http://wiki", transport=httpx.MockTransport(handler))
    assert page is not None
    assert page["markdown"] == "# Payments\n\nbody"
    assert page["version"] == 2


async def test_get_wiki_page_missing_returns_none():
    page = await get_wiki_page(
        "missing",
        base="http://wiki",
        transport=httpx.MockTransport(lambda r: httpx.Response(404)),
    )
    assert page is None


async def test_list_spaces_forwards_identity_and_shapes():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/spaces"
        assert request.headers.get("X-User-Id")  # permission-aware: identity fwd
        return httpx.Response(
            200,
            json=[
                {
                    "slug": "user-alice",
                    "name": "Personal",
                    "kind": "personal",
                    "item_count": 3,
                },
                {"slug": "acme", "name": "Acme", "kind": "team", "item_count": 24},
                {
                    "slug": "engineering",
                    "name": "Public",
                    "kind": "public",
                    "item_count": 216,
                },
            ],
        )

    spaces = await list_spaces(base="http://wiki", transport=httpx.MockTransport(handler))
    assert [s["slug"] for s in spaces] == ["user-alice", "acme", "engineering"]
    assert spaces[1] == {
        "slug": "acme",
        "name": "Acme",
        "kind": "team",
        "item_count": 24,
    }


async def test_search_wiki_scopes_to_spaces():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search"
        # repeated ?space= → union
        seen["spaces"] = [v for k, v in request.url.params.multi_items() if k == "space"]
        return httpx.Response(200, json={"hits": []})

    await search_wiki(
        "q",
        spaces=["acme", "personal"],
        base="http://wiki",
        transport=httpx.MockTransport(handler),
    )
    assert seen["spaces"] == ["acme", "personal"]


async def test_search_wiki_omits_space_when_unscoped():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["spaces"] = [v for k, v in request.url.params.multi_items() if k == "space"]
        return httpx.Response(200, json={"hits": []})

    await search_wiki("q", base="http://wiki", transport=httpx.MockTransport(handler))
    assert seen["spaces"] == []  # no ?space= when unscoped
