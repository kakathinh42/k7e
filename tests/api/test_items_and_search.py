"""Tests for items and search API (Task 3.3).

TDD: tests written BEFORE implementation.

Uses an in-memory SQLite database with StaticPool; ``Base.metadata.create_all``
creates all tables. One published KnowledgeItem is seeded using
``upsert_item_version`` so the full versioning + gate pipeline is exercised.

All external dependencies are overridden:
- ``k7e_api.db.get_session`` -> SQLite session (via StaticPool)
- ``get_principal`` / ``get_authz`` use default MVP values (dev/reviewer, all allowed).

The seeded item's title contains the unique word "ChatAgentMCP" so search can
find it unambiguously.
"""

from __future__ import annotations

import uuid
from typing import Generator

import k7e_api.db as db_module
import pytest
from fastapi.testclient import TestClient
from k7e_api.deps import get_embedding_client
from k7e_api.embedding_client import StubEmbeddingClient
from k7e_api.gate import GateOutcome
from k7e_api.interpretation import Citation, Interpretation
from k7e_api.main import app
from k7e_api.models import Base, KnowledgeItem, RawDocument, Source
from k7e_api.tenancy import get_tenant_context
from k7e_api.versioning import upsert_item_version
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

from tests.api.conftest import TEST_TENANT_CONTEXT

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RAW_DOC_ID = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
_CITATION_RAW_DOC_ID = uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
_UNIQUE_WORD = "ChatAgentMCP"
_ITEM_SLUG = "chat-agent-mcp"
_ITEM_TITLE = f"{_UNIQUE_WORD} Integration Guide"
_MARKDOWN_BODY = (
    f"# {_UNIQUE_WORD}\n\n"
    "This guide explains how to integrate the ChatAgentMCP system "
    "into your existing workflow. It uses a modern protocol for LLM agents."
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sqlite_engine():
    """Create a shared in-memory SQLite engine with all tables."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(scope="module")
def sqlite_session_factory(sqlite_engine):
    """Return a sessionmaker bound to the shared SQLite engine."""
    return sessionmaker(sqlite_engine, expire_on_commit=False, class_=Session)


@pytest.fixture(scope="module")
def seeded_item_slug(sqlite_session_factory) -> str:
    """Seed a published KnowledgeItem using upsert_item_version and return its slug.

    Seeding order:
    1. Source row
    2. RawDocument row
    3. upsert_item_version with publish GateOutcome
    """
    session = sqlite_session_factory()
    try:
        # 1. Create a Source
        source = Source(name="test-source-3.3")
        session.add(source)
        session.flush()

        # 2. Create a RawDocument
        raw_doc = RawDocument(
            id=_RAW_DOC_ID,
            source_id=source.id,
            filename="chat-agent-mcp.md",
            sha256="a" * 64,
            object_store_ref="raw/test/chat-agent-mcp.md",
            mime_type="text/markdown",
            size_bytes=len(_MARKDOWN_BODY),
            status="done",
        )
        session.add(raw_doc)
        session.flush()

        # 3. Build Interpretation with unique word in title
        interp = Interpretation(
            title=_ITEM_TITLE,
            slug=_ITEM_SLUG,
            summary="A guide on ChatAgentMCP integration.",
            markdown_body=_MARKDOWN_BODY,
            confidence=0.95,
            citations=[
                Citation(
                    raw_document_id=_CITATION_RAW_DOC_ID,
                    quote="modern protocol for LLM agents",
                )
            ],
        )

        # 4. Use publish gate so item becomes "published"
        gate = GateOutcome(decision="publish", reasons=[])

        upsert_item_version(
            session,
            interp=interp,
            raw_document_id=_RAW_DOC_ID,
            model_id="test-model",
            gate=gate,
            created_by="test-seeder",
        )
        session.commit()

        # Confirm item is published
        item = session.execute(
            __import__("sqlalchemy").select(KnowledgeItem).where(KnowledgeItem.slug == _ITEM_SLUG)
        ).scalar_one()
        assert item.status == "published", f"Expected published, got: {item.status}"
        assert item.current_version_id is not None

        return _ITEM_SLUG
    finally:
        session.close()


@pytest.fixture(scope="module")
def client(sqlite_session_factory, seeded_item_slug):
    """Return a TestClient with get_session overridden to use the shared SQLite DB."""

    def override_get_session() -> Generator[Session, None, None]:
        session = sqlite_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[db_module.get_session] = override_get_session
    app.dependency_overrides[get_embedding_client] = lambda: StubEmbeddingClient()
    app.dependency_overrides[get_tenant_context] = lambda: TEST_TENANT_CONTEXT
    yield TestClient(app)
    app.dependency_overrides.pop(db_module.get_session, None)
    app.dependency_overrides.pop(get_embedding_client, None)
    app.dependency_overrides.pop(get_tenant_context, None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestListItems:
    """GET /items returns published items."""

    def test_list_items_returns_published(self, client):
        """GET /items must include the seeded published item."""
        response = client.get("/items")
        assert response.status_code == 200, response.text
        data = response.json()
        assert isinstance(data, list)
        slugs = [item["slug"] for item in data]
        assert _ITEM_SLUG in slugs, f"Expected {_ITEM_SLUG!r} in {slugs}"

    def test_list_items_response_shape(self, client):
        """Each item in GET /items must have the required fields."""
        response = client.get("/items")
        assert response.status_code == 200
        data = response.json()
        item = next(i for i in data if i["slug"] == _ITEM_SLUG)
        assert "id" in item
        assert "slug" in item
        assert "title" in item
        assert "status" in item
        assert "updated_at" in item
        assert "type" in item
        assert "space" in item  # space ref (may be null if the item has no space)
        assert item["status"] == "published"


class TestSpaces:
    """GET /spaces lists the caller's accessible spaces with kinds + counts."""

    def test_list_spaces_shape(self, client):
        response = client.get("/spaces")
        assert response.status_code == 200, response.text
        data = response.json()
        assert isinstance(data, list)
        for s in data:
            assert set(s.keys()) >= {"slug", "name", "kind", "item_count"}
            assert s["kind"] in ("personal", "team", "public")
            assert isinstance(s["item_count"], int)


class TestGetItemDetail:
    """GET /items/{slug} returns full item detail."""

    def test_get_item_returns_detail(self, client):
        """GET /items/{slug} returns markdown_body and version number."""
        response = client.get(f"/items/{_ITEM_SLUG}")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["slug"] == _ITEM_SLUG
        assert data["title"] == _ITEM_TITLE
        assert "markdown_body" in data
        assert _UNIQUE_WORD in data["markdown_body"]
        assert "version" in data
        assert data["version"] >= 1

    def test_get_item_includes_citations(self, client):
        """GET /items/{slug} must include a citations list."""
        response = client.get(f"/items/{_ITEM_SLUG}")
        assert response.status_code == 200
        data = response.json()
        assert "citations" in data
        assert isinstance(data["citations"], list)

    def test_get_item_includes_model_id(self, client):
        """GET /items/{slug} must include the model_id field."""
        response = client.get(f"/items/{_ITEM_SLUG}")
        assert response.status_code == 200
        data = response.json()
        assert "model_id" in data

    def test_get_item_404_for_unknown_slug(self, client):
        """GET /items/{slug} with an unknown slug returns 404."""
        response = client.get("/items/totally-nonexistent-slug-xyz-123")
        assert response.status_code == 404, response.text


class TestSearch:
    """GET /search?q=... returns matching items."""

    def test_search_returns_hit_after_publish(self, client):
        """GET /search?q=ChatAgentMCP must return the seeded published item."""
        response = client.get(f"/search?q={_UNIQUE_WORD}")
        assert response.status_code == 200, response.text
        data = response.json()
        assert "hits" in data
        hits = data["hits"]
        assert len(hits) >= 1, f"Expected at least 1 hit, got: {hits}"
        slugs = [h["slug"] for h in hits]
        assert _ITEM_SLUG in slugs, f"Expected {_ITEM_SLUG!r} in {slugs}"

    def test_search_hit_has_required_fields(self, client):
        """Each search hit must have id, slug, title, snippet, and score."""
        response = client.get(f"/search?q={_UNIQUE_WORD}")
        assert response.status_code == 200
        data = response.json()
        hit = next(h for h in data["hits"] if h["slug"] == _ITEM_SLUG)
        assert "id" in hit
        assert "slug" in hit
        assert "title" in hit
        assert "snippet" in hit
        assert "score" in hit

    def test_search_no_results_for_unknown_query(self, client):
        """GET /search?q=<nonexistent> returns empty hits list."""
        response = client.get("/search?q=zzz-nonexistent-term-xyz-987")
        assert response.status_code == 200
        data = response.json()
        assert data["hits"] == []

    def test_search_default_limit(self, client):
        """GET /search without explicit limit defaults to 20 or fewer results."""
        response = client.get(f"/search?q={_UNIQUE_WORD}")
        assert response.status_code == 200
        data = response.json()
        assert len(data["hits"]) <= 20

    def test_search_degrades_to_keyword_when_embedder_fails(self, client):
        """A rate-limited query embed must NOT 500 search — keyword still works."""

        class _RaisingEmbedder:
            async def embed(self, texts):
                raise RuntimeError("429 rate limit")

        app.dependency_overrides[get_embedding_client] = lambda: _RaisingEmbedder()
        try:
            response = client.get(f"/search?q={_UNIQUE_WORD}")
            assert response.status_code == 200
            assert any(h["slug"] for h in response.json()["hits"])  # keyword matched
        finally:
            app.dependency_overrides[get_embedding_client] = lambda: StubEmbeddingClient()
