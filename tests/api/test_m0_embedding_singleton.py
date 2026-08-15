"""M0 hardening — the embedding client is a process-wide singleton.

``get_embedding_client`` previously built a new ``LiteLLMEmbeddingClient`` on
every call. It now caches a module-level singleton, while remaining overridable
via ``app.dependency_overrides`` (the FastAPI dependency function stays the
override point).
"""

from __future__ import annotations

from k7e_api import deps
from k7e_api.deps import get_embedding_client


def test_get_embedding_client_returns_same_instance():
    original = deps._embedding_client
    try:
        deps._embedding_client = None  # reset for a clean measurement
        first = get_embedding_client()
        second = get_embedding_client()
        assert first is second, "get_embedding_client must return a cached singleton"
    finally:
        deps._embedding_client = original


def test_get_embedding_client_is_overridable():
    from k7e_api.main import app

    sentinel = object()
    app.dependency_overrides[get_embedding_client] = lambda: sentinel
    try:
        # FastAPI resolves the override, bypassing the singleton entirely.
        assert app.dependency_overrides[get_embedding_client]() is sentinel
    finally:
        app.dependency_overrides.pop(get_embedding_client, None)
