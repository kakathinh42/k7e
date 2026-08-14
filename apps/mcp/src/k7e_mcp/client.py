"""Thin async client over the k7e HTTP retrieval API.

Kept separate from the MCP wiring so it can be imported and unit-tested (and
reused by the token-savings POC) without standing up an MCP transport. Every
request carries the caller identity headers the k7e auth seam expects, so
retrieval stays permission-aware.
"""

from __future__ import annotations

import os

import httpx

DEFAULT_BASE = os.environ.get("K7E_API_BASE", "http://localhost:8001")


def _headers(
    authorization: str | None = None,
    *,
    app_key: str | None = None,
    on_behalf_email: str | None = None,
) -> dict[str, str]:
    # Delegated on-behalf identity wins (per-user retrieval); then a forwarded
    # bearer; else the fixed service identity (dev / stdio).
    if app_key and on_behalf_email:
        return {"X-App-Key": app_key, "X-On-Behalf-Of-Email": on_behalf_email}
    if authorization:
        return {"Authorization": authorization}
    return {
        "X-User-Id": os.environ.get("WIKI_USER_ID", "chat-agent"),
        "X-User-Roles": os.environ.get("WIKI_USER_ROLES", "reader"),
    }


async def search_wiki(
    query: str,
    limit: int = 5,
    *,
    spaces: list[str] | None = None,
    base: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    authorization: str | None = None,
    app_key: str | None = None,
    on_behalf_email: str | None = None,
) -> list[dict]:
    """Search compiled wiki pages; return up to ``limit`` compact hits.

    Each hit is ``{slug, title, snippet, score}`` — the snippet is a short
    extract of the *compiled* page, i.e. far fewer tokens than the raw source.
    ``spaces`` (slugs from :func:`list_spaces`) scopes the search to the union of
    those spaces; omitted → every space the caller can read.
    """
    params: dict = {"q": query}
    if spaces:
        params["space"] = spaces  # httpx repeats: ?space=a&space=b (union)
    async with httpx.AsyncClient(
        base_url=base or DEFAULT_BASE,
        headers=_headers(authorization, app_key=app_key, on_behalf_email=on_behalf_email),
        timeout=15,
        transport=transport,
    ) as client:
        resp = await client.get("/search", params=params)
        resp.raise_for_status()
        hits = resp.json().get("hits", [])[:limit]
    return [
        {
            "slug": h["slug"],
            "title": h["title"],
            "snippet": h.get("snippet", ""),
            "score": h.get("score", 0.0),
        }
        for h in hits
    ]


async def list_spaces(
    *,
    base: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    authorization: str | None = None,
    app_key: str | None = None,
    on_behalf_email: str | None = None,
) -> list[dict]:
    """Return the spaces the caller (their PAT/identity) can read.

    Each entry is ``{slug, name, kind, item_count}`` with ``kind`` one of
    ``personal`` / ``team`` / ``public``. Use it to discover which spaces a PAT
    unlocks and to pick ``spaces`` slugs for :func:`search_wiki`.
    """
    async with httpx.AsyncClient(
        base_url=base or DEFAULT_BASE,
        headers=_headers(authorization, app_key=app_key, on_behalf_email=on_behalf_email),
        timeout=15,
        transport=transport,
    ) as client:
        resp = await client.get("/spaces")
        resp.raise_for_status()
        spaces = resp.json()
    return [
        {
            "slug": s["slug"],
            "name": s["name"],
            "kind": s["kind"],
            "item_count": s.get("item_count", 0),
        }
        for s in spaces
    ]


async def get_wiki_page(
    slug: str,
    *,
    base: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    authorization: str | None = None,
    app_key: str | None = None,
    on_behalf_email: str | None = None,
) -> dict | None:
    """Return the full compiled Markdown page for ``slug`` (or None if absent)."""
    async with httpx.AsyncClient(
        base_url=base or DEFAULT_BASE,
        headers=_headers(authorization, app_key=app_key, on_behalf_email=on_behalf_email),
        timeout=15,
        transport=transport,
    ) as client:
        resp = await client.get(f"/items/{slug}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
    return {
        "slug": data["slug"],
        "title": data["title"],
        "markdown": data["markdown_body"],
        "version": data.get("version"),
        "citations": data.get("citations", []),
    }


async def save_to_wiki(
    content: str,
    title: str = "Saved note",
    *,
    base: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    authorization: str | None = None,
    app_key: str | None = None,
    on_behalf_email: str | None = None,
) -> dict:
    """Ingest ``content`` into the caller's PERSONAL wiki space as Markdown.

    Authenticated by the forwarded credential (e.g. a PAT → the token owner);
    ``space="personal"`` routes it to that user's private space. Returns the
    ingest job info (``raw_document_id`` / ``workflow_id``); the page is
    compiled asynchronously. Raises ``httpx.HTTPStatusError`` on a non-2xx.
    """
    safe = "".join(c if c.isalnum() or c in "-_ " else "-" for c in title).strip() or "note"
    async with httpx.AsyncClient(
        base_url=base or DEFAULT_BASE,
        headers=_headers(authorization, app_key=app_key, on_behalf_email=on_behalf_email),
        timeout=30,
        transport=transport,
    ) as client:
        resp = await client.post(
            "/ingest/upload",
            files={"file": (f"{safe}.md", content.encode("utf-8"), "text/markdown")},
            data={"source_system": "chat_agent", "space": "personal"},
        )
        resp.raise_for_status()
        return resp.json()
