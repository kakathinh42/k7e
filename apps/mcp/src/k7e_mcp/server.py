"""k7e MCP server (stdio).

Exposes the compiled-knowledge retrieval surface as MCP tools so chat-agent (or
any MCP client — Claude Desktop, etc.) can read compact, citation-backed wiki
pages instead of dumping large raw documents into the model context.

Run it::

    K7E_API_BASE=http://localhost:8001 k7e-mcp

See README.md for the chat-agent / Claude Desktop config snippet.
"""

from __future__ import annotations

from mcp.server.fastmcp import Context, FastMCP

from k7e_mcp.client import get_wiki_page as _get_wiki_page
from k7e_mcp.client import list_spaces as _list_spaces
from k7e_mcp.client import save_to_wiki as _save_to_wiki
from k7e_mcp.client import search_wiki as _search_wiki

mcp = FastMCP("k7e")


def _forward(ctx: "Context | None") -> tuple[str | None, str | None, str | None]:
    """Best-effort read of the incoming HTTP request's identity headers.

    Returns ``(authorization, app_key, on_behalf_email)``. Present on
    streamable-http transport (chat-agent forwards the user's JWT, or the
    delegated ``X-App-Key`` + ``X-On-Behalf-Of-Email`` pair for per-user
    retrieval); absent on stdio/desktop → all None so the client falls back to
    the env identity. Never raises — the server relays what it sees, verifies
    nothing.
    """
    try:
        request = ctx.request_context.request  # type: ignore[union-attr]
        if request is None:
            return None, None, None
        h = request.headers
        return (
            h.get("authorization"),
            h.get("x-app-key"),
            h.get("x-on-behalf-of-email"),
        )
    except (AttributeError, ValueError):
        # AttributeError: no ctx/request (stdio). ValueError: FastMCP raises it
        # when request_context is accessed outside a request. Either → no token.
        return None, None, None


def _authorization(ctx: "Context | None") -> str | None:
    """Backward-compatible authorization-only view of ``_forward``."""
    return _forward(ctx)[0]


@mcp.tool()
async def list_wiki_spaces(ctx: Context = None) -> list[dict]:
    """List the wiki spaces the caller can read — personal, team, and public.

    Use this to discover which spaces the caller's credential (e.g. a PAT)
    unlocks before searching. Each entry is ``{slug, name, kind, item_count}``
    with ``kind`` one of ``personal`` / ``team`` / ``public``. Pass one or more
    of the returned ``slug`` values as ``spaces`` to ``search_wiki`` to scope a
    query to just those spaces (e.g. only a specific team).
    """
    authz, app_key, obo = _forward(ctx)
    return await _list_spaces(authorization=authz, app_key=app_key, on_behalf_email=obo)


@mcp.tool()
async def search_wiki(
    query: str,
    limit: int = 5,
    spaces: list[str] | None = None,
    ctx: Context = None,
) -> list[dict]:
    """Search the company knowledge wiki and return compact, citation-backed hits.

    Prefer this over reading raw source documents: each result is a short
    snippet of a *compiled* wiki page, so answering a question costs far fewer
    tokens. Use it first for questions about company systems, decisions,
    runbooks, incidents, and ownership. Each hit has ``slug``, ``title``,
    ``snippet`` and a relevance ``score``; pass a ``slug`` to ``get_wiki_page``
    for the full page.

    ``spaces`` optionally scopes the search to the union of the given space slugs
    (from ``list_wiki_spaces``) — e.g. ``["acme"]`` to search only that team.
    Omit it to search every space the caller can read.
    """
    authz, app_key, obo = _forward(ctx)
    return await _search_wiki(
        query,
        limit,
        spaces=spaces,
        authorization=authz,
        app_key=app_key,
        on_behalf_email=obo,
    )


@mcp.tool()
async def get_wiki_page(slug: str, ctx: Context = None) -> dict | None:
    """Return the full compiled Markdown wiki page for ``slug`` (from search results).

    The body is already synthesized and cross-linked at ingest time, so it is
    concise and citation-backed — much smaller than the original source docs.
    """
    authz, app_key, obo = _forward(ctx)
    return await _get_wiki_page(slug, authorization=authz, app_key=app_key, on_behalf_email=obo)


@mcp.tool()
async def save_to_wiki(content: str, title: str = "Saved note", ctx: Context = None) -> dict:
    """Save text into YOUR personal wiki space — a note, a summary, a useful
    answer, or a conversation excerpt.

    Use this when the user asks to remember/save/note something to the wiki. The
    content is compiled into a citation-backed page visible only to you (your
    personal space), authenticated as you via the forwarded credential. Returns
    the ingest job id; compilation runs asynchronously.
    """
    authz, app_key, obo = _forward(ctx)
    return await _save_to_wiki(
        content, title, authorization=authz, app_key=app_key, on_behalf_email=obo
    )


def main() -> None:
    """Console-script entrypoint: serve over stdio (for stdio MCP clients)."""
    mcp.run()


def main_http() -> None:
    """Console-script entrypoint: serve over streamable-http at ``/mcp``.

    Use this for network MCP clients (e.g. chat-agent connects to a
    ``streamable-http`` URL). Host/port via ``K7E_MCP_HOST`` / ``K7E_MCP_PORT``
    (default 0.0.0.0:9100); the k7e API origin via ``K7E_API_BASE``.
    """
    import os

    from mcp.server.transport_security import TransportSecuritySettings

    mcp.settings.host = os.environ.get("K7E_MCP_HOST", "0.0.0.0")
    mcp.settings.port = int(os.environ.get("K7E_MCP_PORT", "9100"))
    # This server is reached server-to-server — directly, or via the MCP gateway
    # (chat-agent -> mcp-servers -> here) over the Docker host, so requests arrive
    # with non-local Host headers (e.g. host.docker.internal). FastMCP's default
    # DNS-rebinding protection (a browser defense) would reject those with HTTP
    # 421; disable it for this internal endpoint.
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    )
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
