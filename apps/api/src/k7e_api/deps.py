"""FastAPI dependency factories for injectable services.

All external-service dependencies live here so tests can override them via
``app.dependency_overrides`` without importing production drivers.

Design constraints:
- ``get_object_store`` returns a ``LocalFileObjectStore`` by default.
- ``get_workflow_starter`` returns the async ``start_ingest_workflow`` function
  from ``k7e_api.temporal_client``.  The router calls the starter and, if the
  result is awaitable (i.e. the production async function was used), awaits it.
  Sync test fakes that return a plain string are also supported because a plain
  string is not awaitable — the router handles both cases transparently.
- Importing *this* module never triggers a Temporal SDK connection: the
  ``temporalio.client.Client.connect`` call only happens when the returned
  async callable is eventually invoked inside a request handler.
"""

from __future__ import annotations

from typing import Callable

from k7e_api.config import get_settings
from k7e_api.object_store import LocalFileObjectStore, ObjectStore


def get_object_store() -> ObjectStore:
    """Return the configured object store instance.

    Default: a ``LocalFileObjectStore`` rooted at ``Settings.object_store_path``.
    Override in tests via ``app.dependency_overrides[get_object_store]``.
    """
    return LocalFileObjectStore(get_settings().object_store_path)


def get_workflow_starter() -> Callable[[str], object]:
    """Return a callable that starts the ingest Temporal workflow.

    The returned callable has signature ``start(raw_document_id: str)``.

    For the production default, this is the **async** coroutine function
    ``k7e_api.temporal_client.start_ingest_workflow``.  The ingest route
    inspects the return value with ``inspect.isawaitable`` and awaits it when
    necessary, so sync test fakes that return a plain string continue to work
    unchanged.

    The ``temporal_client`` module is lazily imported here (inside the body of
    ``get_workflow_starter``) so that importing *this* module does **not**
    require a running Temporal server and does not pull in ``temporalio`` at
    import time if the module is not yet installed.
    """
    from k7e_api.temporal_client import start_ingest_workflow  # noqa: PLC0415

    return start_ingest_workflow


_embedding_client = None


def get_embedding_client():
    """Return the process-wide embedding client (override in tests with StubEmbeddingClient).

    M0 perf: the embedding client is constructed once and cached as a module-level
    singleton. ``EMBEDDING_CLIENT_IMPL=stub`` selects the deterministic
    ``StubEmbeddingClient`` (offline demo); otherwise ``LiteLLMEmbeddingClient``.
    Tests still override the whole dependency via
    ``app.dependency_overrides[get_embedding_client]`` — the singleton is only
    used when the dependency is not overridden.
    """
    import os

    global _embedding_client
    if _embedding_client is None:
        if os.environ.get("EMBEDDING_CLIENT_IMPL", "litellm").lower() == "stub":
            from k7e_api.embedding_client import StubEmbeddingClient  # noqa: PLC0415

            _embedding_client = StubEmbeddingClient()
        else:
            from k7e_api.embedding_client import LiteLLMEmbeddingClient  # noqa: PLC0415

            _embedding_client = LiteLLMEmbeddingClient()
    return _embedding_client


def get_llm_client():
    """Return the active LLM client (override in tests with StubLLMClient).

    ``LLM_CLIENT_IMPL=stub`` selects the deterministic ``StubLLMClient`` (offline
    demo); otherwise the production ``LiteLLMClient``.
    """
    import os

    if os.environ.get("LLM_CLIENT_IMPL", "litellm").lower() == "stub":
        from k7e_api.llm_client import StubLLMClient  # noqa: PLC0415

        return StubLLMClient()
    from k7e_api.llm_client import LiteLLMClient  # noqa: PLC0415

    return LiteLLMClient()
