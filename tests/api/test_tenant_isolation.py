"""Cross-tenant isolation guard tests (Task 5 — M1 multi-org foundation).

Two concerns are verified:

1. **Cross-tenant isolation (Step 5.1):** A second org's items are completely
   invisible to the default (first) org's API context.  /items, /search, and
   /graph under org A must never return org B's slugs or titles.

2. **Un-scoped-query guard (Step 5.2):** A static grep-based lint confirms that
   every ``select(KnowledgeItem)`` call inside the router files is wrapped by
   ``scoped()``.  This catches any router that forgets the org filter.

Critical caveat from the Task 4 review
---------------------------------------
``scoped()`` uses ``WHERE org_id = ctx.org_id OR org_id IS NULL`` in Phase 1.
Any item whose ``org_id`` is ``None`` would leak to BOTH org contexts.  Every
seeded item in these tests therefore carries an **explicit** ``org_id`` so that
the OR-IS-NULL arm is never the reason a row appears.

Context alignment
-----------------
The shared ``api_client`` fixture (conftest.py) overrides ``get_tenant_context``
to return ``TEST_TENANT_CONTEXT`` whose ``org_id`` is:

    00000000-0000-0000-0000-000000000001

Org A in this file uses that exact UUID so the fixture's dependency override
routes the HTTP requests to org A's rows without any extra setup.  Org B uses a
different UUID so its rows are invisible to the default client.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import k7e_api.db as db_module
import pytest
from fastapi.testclient import TestClient
from k7e_api.deps import get_embedding_client
from k7e_api.embedding_client import StubEmbeddingClient
from k7e_api.main import app
from k7e_api.models import (
    KnowledgeItem,
    KnowledgeItemVersion,
    Organization,
    Space,
)
from k7e_api.tenancy import TenantContext, get_tenant_context
from sqlalchemy.orm import Session

from tests.api.conftest import TEST_TENANT_CONTEXT

# ---------------------------------------------------------------------------
# Constants — keep them named so the assertions below are self-documenting
# ---------------------------------------------------------------------------

# Org A: aligned to TEST_TENANT_CONTEXT so the default api_client fixture works.
_ORG_A_ID = TEST_TENANT_CONTEXT.org_id  # 00000000-0000-0000-0000-000000000001
_ORG_B_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")

_ORG_A_SLUG = "acme-alpha"
_ORG_B_SLUG = "acme-beta"

# Unique distinguishing words make assertions easy and search unambiguous.
_ORG_A_UNIQUE = "OrgAlphaUniqueXYZ"
_ORG_B_UNIQUE = "OrgBetaUniqueXYZ"

_ORG_A_ITEMS = [
    ("alpha-item-1", f"{_ORG_A_UNIQUE} First Article"),
    ("alpha-item-2", f"{_ORG_A_UNIQUE} Second Article"),
    ("alpha-item-3", f"{_ORG_A_UNIQUE} Third Article"),
]
_ORG_B_ITEMS = [
    ("beta-item-1", f"{_ORG_B_UNIQUE} First Article"),
    ("beta-item-2", f"{_ORG_B_UNIQUE} Second Article"),
    ("beta-item-3", f"{_ORG_B_UNIQUE} Third Article"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _seed_published_item(
    session: Session,
    org_id: uuid.UUID,
    space_id: uuid.UUID,
    slug: str,
    title: str,
) -> KnowledgeItem:
    """Seed a published KnowledgeItem with explicit org_id/space_id.

    IMPORTANT: org_id is set explicitly on BOTH item and version so that the
    Phase 1 ``OR org_id IS NULL`` arm in ``scoped()`` cannot cause cross-tenant
    leakage.  A None org_id would make the row visible to every org context.
    """
    item = KnowledgeItem(
        org_id=org_id,  # EXPLICIT — never None
        space_id=space_id,
        slug=slug,
        title=title,
        status="draft",
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(item)
    session.flush()

    version = KnowledgeItemVersion(
        item_id=item.id,
        version_number=1,
        markdown_body=f"# {title}\n\nBody text for {title}.",
        model_id="wiki-default",
        created_by="test-seeder",
        status="published",
        title=title,
        citations=[],
        created_at=_now(),
    )
    session.add(version)
    session.flush()

    item.current_version_id = version.id
    item.status = "published"
    session.flush()
    return item


def _seed_two_orgs(session: Session) -> tuple[Space, Space]:
    """Seed two organisations each with one space and their items.

    Returns (space_a, space_b).  All items carry explicit org_id values.
    """
    org_a = Organization(id=_ORG_A_ID, slug=_ORG_A_SLUG, name="Alpha Org")
    org_b = Organization(id=_ORG_B_ID, slug=_ORG_B_SLUG, name="Beta Org")
    session.add_all([org_a, org_b])
    session.flush()

    space_a = Space(org_id=_ORG_A_ID, slug="eng-a", name="Engineering A")
    space_b = Space(org_id=_ORG_B_ID, slug="eng-b", name="Engineering B")
    session.add_all([space_a, space_b])
    session.flush()

    for slug, title in _ORG_A_ITEMS:
        _seed_published_item(session, _ORG_A_ID, space_a.id, slug, title)

    for slug, title in _ORG_B_ITEMS:
        _seed_published_item(session, _ORG_B_ID, space_b.id, slug, title)

    session.commit()
    return space_a, space_b


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolation_client(sqlite_factory):
    """A TestClient scoped to org A.

    Uses the same ``get_tenant_context`` override as the standard ``api_client``
    fixture (returns ``TEST_TENANT_CONTEXT`` whose org_id == _ORG_A_ID) so that
    every HTTP request goes through org A's tenant filter.

    A fresh in-memory SQLite DB is seeded with two orgs before the client is
    returned.
    """

    def _override_get_session():
        session = sqlite_factory()
        try:
            yield session
        finally:
            session.close()

    def _override_get_tenant_context():
        return TenantContext(org_id=_ORG_A_ID)

    # Seed the two orgs into the in-memory DB
    with sqlite_factory() as seed_session:
        _seed_two_orgs(seed_session)

    app.dependency_overrides[db_module.get_session] = _override_get_session
    app.dependency_overrides[get_tenant_context] = _override_get_tenant_context
    app.dependency_overrides[get_embedding_client] = lambda: StubEmbeddingClient()
    yield TestClient(app)
    app.dependency_overrides.pop(db_module.get_session, None)
    app.dependency_overrides.pop(get_tenant_context, None)
    app.dependency_overrides.pop(get_embedding_client, None)


# ---------------------------------------------------------------------------
# Step 5.1 — Cross-tenant isolation: /items, /search, /graph
# ---------------------------------------------------------------------------


class TestCrossTenantIsolationItems:
    """GET /items under org A must not expose org B's rows."""

    def test_list_items_returns_only_org_a(self, isolation_client):
        """Org A's /items must contain only org A items — no org B slugs."""
        response = isolation_client.get("/items")
        assert response.status_code == 200, response.text
        data = response.json()
        returned_slugs = {item["slug"] for item in data}

        # All org A items must be visible.
        for slug, _ in _ORG_A_ITEMS:
            assert slug in returned_slugs, (
                f"Org A item {slug!r} missing from /items response: {returned_slugs}"
            )

        # No org B item must be visible — this is the isolation assertion.
        for slug, _ in _ORG_B_ITEMS:
            assert slug not in returned_slugs, (
                f"Org B item {slug!r} leaked into org A's /items response! "
                f"(org_id isolation broken)"
            )

    def test_list_items_org_b_titles_absent(self, isolation_client):
        """Org B's unique title tokens must not appear in any /items response title."""
        response = isolation_client.get("/items")
        assert response.status_code == 200, response.text
        all_titles = " ".join(item["title"] for item in response.json())
        assert _ORG_B_UNIQUE not in all_titles, (
            f"Org B unique token {_ORG_B_UNIQUE!r} found in /items titles — "
            f"cross-tenant data leaked!"
        )

    def test_list_items_correct_count(self, isolation_client):
        """Org A's /items must return exactly the 3 seeded org A items."""
        response = isolation_client.get("/items")
        assert response.status_code == 200, response.text
        data = response.json()
        assert len(data) == len(_ORG_A_ITEMS), (
            f"Expected {len(_ORG_A_ITEMS)} items for org A, got {len(data)}: "
            f"{[i['slug'] for i in data]}"
        )

    def test_get_item_by_slug_org_b_returns_404(self, isolation_client):
        """GET /items/<org-b-slug> under org A's context must return 404."""
        beta_slug = _ORG_B_ITEMS[0][0]  # "beta-item-1"
        response = isolation_client.get(f"/items/{beta_slug}")
        assert response.status_code == 404, (
            f"Expected 404 for org B item {beta_slug!r} under org A context, "
            f"got {response.status_code}: {response.text}"
        )

    def test_get_item_by_slug_org_a_accessible(self, isolation_client):
        """GET /items/<org-a-slug> under org A's context must return 200."""
        alpha_slug = _ORG_A_ITEMS[0][0]  # "alpha-item-1"
        response = isolation_client.get(f"/items/{alpha_slug}")
        assert response.status_code == 200, (
            f"Org A item {alpha_slug!r} must be accessible under org A context, "
            f"got {response.status_code}: {response.text}"
        )


class TestCrossTenantIsolationSearch:
    """GET /search under org A must not return org B's items."""

    def test_search_org_a_unique_token_returns_org_a_only(self, isolation_client):
        """Searching for org A's unique token must return only org A hits."""
        response = isolation_client.get(f"/search?q={_ORG_A_UNIQUE}")
        assert response.status_code == 200, response.text
        data = response.json()
        hits = data["hits"]
        assert len(hits) >= 1, f"Expected at least 1 hit for {_ORG_A_UNIQUE!r}, got none"
        hit_slugs = {h["slug"] for h in hits}
        for slug, _ in _ORG_B_ITEMS:
            assert slug not in hit_slugs, (
                f"Org B item {slug!r} leaked into search results for "
                f"{_ORG_A_UNIQUE!r}. Cross-tenant isolation broken."
            )

    def test_search_org_b_unique_token_returns_no_results(self, isolation_client):
        """Searching for org B's unique token under org A context must return no hits.

        Org B's unique token appears only in org B's items.  Under org A's context,
        those items must be invisible — even when the search query directly matches
        org B's titles.
        """
        response = isolation_client.get(f"/search?q={_ORG_B_UNIQUE}")
        assert response.status_code == 200, response.text
        data = response.json()
        hits = data["hits"]
        assert hits == [], (
            f"Org B items leaked into org A's search for {_ORG_B_UNIQUE!r}: "
            f"{[h['slug'] for h in hits]}"
        )

    def test_search_org_b_item_slugs_absent(self, isolation_client):
        """Search results must not contain any org B slug."""
        response = isolation_client.get("/search?q=Article")
        assert response.status_code == 200, response.text
        hit_slugs = {h["slug"] for h in response.json()["hits"]}
        for slug, _ in _ORG_B_ITEMS:
            assert slug not in hit_slugs, (
                f"Org B slug {slug!r} appeared in org A's search results. "
                f"Cross-tenant isolation broken."
            )


class TestCrossTenantIsolationGraph:
    """GET /graph under org A must not expose org B's nodes."""

    def test_graph_nodes_contain_only_org_a_slugs(self, isolation_client):
        """Graph nodes must include org A slugs and must not include org B slugs."""
        response = isolation_client.get("/graph")
        assert response.status_code == 200, response.text
        body = response.json()
        node_slugs = {n["slug"] for n in body["nodes"]}

        # Org A items must appear as nodes.
        for slug, _ in _ORG_A_ITEMS:
            assert slug in node_slugs, (
                f"Org A item {slug!r} missing from /graph nodes: {node_slugs}"
            )

        # Org B items must NOT appear as nodes.
        for slug, _ in _ORG_B_ITEMS:
            assert slug not in node_slugs, (
                f"Org B item {slug!r} leaked into org A's /graph nodes! "
                f"Cross-tenant isolation broken."
            )

    def test_graph_correct_node_count(self, isolation_client):
        """Graph must contain exactly the 3 org A nodes (no extras from org B)."""
        response = isolation_client.get("/graph")
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body["nodes"]) == len(_ORG_A_ITEMS), (
            f"Expected {len(_ORG_A_ITEMS)} nodes for org A, got "
            f"{len(body['nodes'])}: {[n['slug'] for n in body['nodes']]}"
        )

    def test_graph_org_b_titles_absent_from_nodes(self, isolation_client):
        """Graph node titles must not contain org B's unique token."""
        response = isolation_client.get("/graph")
        assert response.status_code == 200, response.text
        all_titles = " ".join(n["title"] for n in response.json()["nodes"])
        assert _ORG_B_UNIQUE not in all_titles, (
            f"Org B unique token {_ORG_B_UNIQUE!r} found in /graph node titles — "
            f"cross-tenant data leaked!"
        )


# ---------------------------------------------------------------------------
# Step 5.2 — Un-scoped-query guard: static lint over router source files
# ---------------------------------------------------------------------------


class TestUnscopedQueryGuard:
    """Static lint: every tenant-scoped select in routers must use scoped().

    Strategy: grep-based (Option B from the plan).

    For each router file we extract all ``select(KnowledgeItem...)`` call sites
    and verify that the statement returned is passed into ``scoped()``.  We use
    a simple line-proximity check: the ``select(...)`` must appear either:
      - on the same line as ``scoped(``, or
      - within the next 5 lines (to handle multi-line statement construction).

    Legitimately un-scoped selects
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    ``_resolve_provenance`` in ``items.py`` queries ``RawDocument`` and
    ``KnowledgeItem`` WITHOUT org-scoping — this is intentional because those
    lookups are content-hash / slug lookups on the provenance of an ALREADY
    FETCHED (and thus already org-checked) item.  These are whitelisted by
    checking for the helper function name context.

    ``ingest.py``'s ``select(Source)`` is the write path (upload → find/create
    Source); that table query uses the ingest router's ``TenantContext`` and is
    separately reviewed.
    """

    # Router files to inspect.
    _ROUTERS_DIR = (
        Path(__file__).parent.parent.parent / "apps" / "api" / "src" / "k7e_api" / "routers"
    )

    # Tenant-scoped models whose ``select(...)`` calls MUST be wrapped.
    # (Source / IngestRun are handled by the ingest router separately.)
    _SCOPED_MODELS = ("KnowledgeItem", "RawDocument", "WikiChunk")

    # Lines that are known-legitimate un-scoped queries (substring match).
    # These are in _resolve_provenance and are exempt from the guard.
    _WHITELIST_SUBSTRINGS = (
        "_resolve_provenance",  # function def is near the selects
        "RawDocument.sha256 == resource",  # the un-scoped RawDoc lookup
        "KnowledgeItem.slug, KnowledgeItem.title",  # the un-scoped source_pages lookup
    )

    def _load_router_source(self, filename: str) -> list[str]:
        path = self._ROUTERS_DIR / filename
        assert path.exists(), f"Router file not found: {path}"
        return path.read_text().splitlines()

    def _is_whitelisted(self, lines: list[str], line_idx: int) -> bool:
        """Return True if line_idx (or context) is in the whitelist."""
        # Check a window around the line for whitelist markers.
        window_start = max(0, line_idx - 10)
        window_end = min(len(lines), line_idx + 5)
        window = "\n".join(lines[window_start:window_end])
        return any(sub in window for sub in self._WHITELIST_SUBSTRINGS)

    def _check_select_is_scoped(self, filename: str, model: str) -> list[str]:
        """Return a list of violation descriptions for un-scoped selects.

        A violation is a ``select(<model>)`` call that is NOT embedded inside a
        ``scoped(...)`` call within a ±5-line window around it.

        The two common patterns are:

        Pattern A — scoped() wraps select() as an argument (scoped appears BEFORE):
            stmt = scoped(
                select(KnowledgeItem)   # <- select is inside scoped(
                .where(...),
                ctx,
            )

        Pattern B — scoped() is called on the result (scoped appears AFTER):
            stmt = scoped(select(KnowledgeItem).where(...), ctx)

        We therefore check a window of 5 lines BEFORE and 5 lines AFTER the
        select() call, looking for ``scoped(``.

        Known limitation (proximity heuristic)
        ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        This is a static text search, not an AST analysis.  A bare un-scoped
        ``select(KnowledgeItem)`` that happens to sit within 5 lines of a
        *different* legitimately scoped statement would produce a false negative
        (the guard would pass even though the bare select is un-scoped).

        In practice this is acceptable because:
        - Each router's select calls are spread across distinct handler functions
          and are not adjacent to each other.
        - The isolation tests in Step 5.1 provide runtime evidence that the
          actual request path is org-scoped — they would fail if any router
          returned cross-tenant rows.
        - The combination of both checks (static lint + runtime isolation) makes
          a silent regression unlikely.

        Future hardening: replace with an AST-based check that confirms the
        ``select(...)`` node is a direct argument to a ``scoped(...)`` call.
        """
        lines = self._load_router_source(filename)
        violations: list[str] = []

        select_pat = re.compile(rf"select\({re.escape(model)}\b")
        window_size = 5  # lines before and after to inspect

        for idx, line in enumerate(lines):
            if not select_pat.search(line):
                continue
            if self._is_whitelisted(lines, idx):
                continue

            # Expand window both before and after: scoped() may wrap select()
            # (outer call before the line) or chain after it.
            before_start = max(0, idx - window_size)
            after_end = min(len(lines), idx + window_size + 1)
            window = "\n".join(lines[before_start:after_end])
            if "scoped(" not in window:
                violations.append(
                    f"{filename}:{idx + 1}: select({model}) not wrapped in scoped() "
                    f"within ±{window_size} lines — tenant isolation may be broken.\n"
                    f"  Line: {line.strip()}"
                )

        return violations

    def test_items_router_knowledge_item_selects_are_scoped(self):
        """items.py: every select(KnowledgeItem) must be wrapped by scoped()."""
        violations = self._check_select_is_scoped("items.py", "KnowledgeItem")
        assert not violations, (
            "Un-scoped KnowledgeItem select(s) found in items.py:\n" + "\n".join(violations)
        )

    def test_graph_router_knowledge_item_selects_are_scoped(self):
        """graph.py: every select(KnowledgeItem) must be wrapped by scoped()."""
        violations = self._check_select_is_scoped("graph.py", "KnowledgeItem")
        assert not violations, (
            "Un-scoped KnowledgeItem select(s) found in graph.py:\n" + "\n".join(violations)
        )

    def test_search_router_uses_scoped_via_provider(self):
        """search.py: the search router delegates to HybridSearchProvider.query()
        which applies scoped() internally.  We verify that search.py itself does
        NOT contain bare ``select(KnowledgeItem)`` calls (all DB work is in
        search.py module, not the router).
        """
        lines = self._load_router_source("search.py")
        select_pat = re.compile(r"select\(KnowledgeItem\b")
        bare_selects = [
            f"search.py:{i + 1}: {line.strip()}"
            for i, line in enumerate(lines)
            if select_pat.search(line)
        ]
        assert not bare_selects, (
            "search.py router should not contain bare select(KnowledgeItem) calls — "
            "the search provider handles scoping:\n" + "\n".join(bare_selects)
        )

    def test_no_new_unscoped_knowledge_item_selects_added(self):
        """Regression guard: no un-whitelisted bare KnowledgeItem selects in routers.

        This test fails if a future router adds a ``select(KnowledgeItem)`` call
        and forgets to wrap it in ``scoped()``.  It acts as a canary: to add a
        new legitimately un-scoped select (e.g. an admin endpoint that bypasses
        tenant filtering by design), add its identifying substring to
        ``_WHITELIST_SUBSTRINGS`` above with a comment explaining why it is safe.
        """
        router_files = ["items.py", "graph.py", "ingest.py", "search.py"]
        total_violations: list[str] = []
        for fname in router_files:
            total_violations.extend(self._check_select_is_scoped(fname, "KnowledgeItem"))
        assert total_violations == [], (
            "New un-scoped KnowledgeItem select(s) detected in routers:\n"
            + "\n".join(total_violations)
        )
