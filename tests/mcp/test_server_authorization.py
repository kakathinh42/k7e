"""M7 Piece 2: server extracts the incoming Authorization header defensively."""

from __future__ import annotations

from types import SimpleNamespace

from k7e_mcp.server import _authorization


def test_authorization_none_when_no_context():
    assert _authorization(None) is None


def test_authorization_from_http_request_context():
    req = SimpleNamespace(headers={"authorization": "Bearer xyz"})
    ctx = SimpleNamespace(request_context=SimpleNamespace(request=req))
    assert _authorization(ctx) == "Bearer xyz"


def test_authorization_none_for_stdio_context_without_request():
    # stdio transport: request_context exists but has no HTTP request
    ctx = SimpleNamespace(request_context=SimpleNamespace(request=None))
    assert _authorization(ctx) is None


def test_authorization_none_when_context_raises_valueerror():
    # FastMCP's Context.request_context raises ValueError when accessed unbound.
    class _Ctx:
        @property
        def request_context(self):
            raise ValueError("not in a request")

    assert _authorization(_Ctx()) is None
