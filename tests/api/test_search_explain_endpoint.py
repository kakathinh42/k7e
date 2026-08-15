"""GET /search?explain=true returns a per-hit breakdown for any caller who opts in.

Score transparency is available to everyone — the breakdown only annotates hits
the caller can already see, so it is no longer gated to admins.
"""

from __future__ import annotations

from k7e_api.auth import get_authz
from k7e_api.main import app
from k7e_api.models import KnowledgeItem, KnowledgeItemVersion, Organization
from k7e_api.rbac import HierarchicalRbacAuthorizationService

from tests.api.conftest import TEST_TENANT_CONTEXT

_ORG = TEST_TENANT_CONTEXT.org_id


def _seed(sqlite_factory):
    with sqlite_factory() as s:
        s.add(Organization(id=_ORG, slug="test-org", name="Test Org"))
        # NOTE: the conftest `_seed_test_rbac_on_flush` before_flush hook auto-seeds
        # the `group:public viewer @ org:<test org>` grant (migration-0017 analog)
        # when a KnowledgeItem is inserted at the test org, so a normal caller can
        # already read the public item. Seeding it manually here would collide with
        # the hook's insert (UNIQUE constraint on role_grants).
        item = KnowledgeItem(
            slug="points",
            type="concept",
            title="Points expiry",
            status="published",
            org_id=_ORG,
        )
        s.add(item)
        s.flush()
        ver = KnowledgeItemVersion(
            item_id=item.id,
            version_number=1,
            markdown_body="Loyalty points expire after 12 months.",
            model_id="m",
            created_by="t",
            status="published",
            title="Points expiry",
            citations=[],
        )
        s.add(ver)
        s.flush()
        item.current_version_id = ver.id
        s.commit()


def _gated(api_client, sqlite_factory):
    app.dependency_overrides[get_authz] = lambda: HierarchicalRbacAuthorizationService(
        session_factory=sqlite_factory
    )
    return api_client


def test_admin_gets_breakdown(api_client, sqlite_factory):
    _seed(sqlite_factory)
    c = _gated(api_client, sqlite_factory)
    try:
        r = c.get(
            "/search?q=points&explain=true",
            headers={"X-User-Id": "admin1", "X-User-Roles": "admin"},
        )
        assert r.status_code == 200, r.text
        hits = r.json()["hits"]
        assert hits and hits[0]["breakdown"] is not None
    finally:
        app.dependency_overrides.pop(get_authz, None)


def test_non_admin_also_gets_breakdown(api_client, sqlite_factory):
    """Explain is a transparency feature — a non-admin reader who opts in gets it."""
    _seed(sqlite_factory)
    c = _gated(api_client, sqlite_factory)
    try:
        r = c.get(
            "/search?q=points&explain=true",
            headers={"X-User-Id": "reader1", "X-User-Roles": "reader"},
        )
        assert r.status_code == 200, r.text
        hits = r.json()["hits"]
        assert hits, "reader should still see the public item"
        assert hits[0]["breakdown"] is not None
    finally:
        app.dependency_overrides.pop(get_authz, None)
