"""Behavior-preserving RBAC cutover proof (Task 4 — M2).

With ``auth_mode="rbac"`` (the new default), ``get_authz`` returns the
hierarchical RBAC service. This is the end-to-end cutover assertion: under the
default config — no per-test ``get_authz`` override, no ``X-User-Groups`` — a
default caller (implicit ``public`` group, ``X-User-Roles: reviewer``) is
admitted by the seeded ``group:public viewer @ org`` grant and so sees every
published item via ``/items`` exactly as under the legacy group service.

The seeded viewer grant + the item's ``org_id`` are brought into the SQLite
test DB by the ``before_flush`` hook in ``tests/api/conftest.py`` (the
migration-0016/0017 analogs) — this test runs against that realistic
post-migration state, not a hand-rolled service-layer stub.
"""

from __future__ import annotations

from k7e_api.auth import get_authz
from k7e_api.config import Settings, get_settings
from k7e_api.models import KnowledgeItem, KnowledgeItemVersion
from k7e_api.rbac import HierarchicalRbacAuthorizationService
from sqlalchemy.orm import Session


def _publish(session: Session, slug: str, title: str) -> KnowledgeItem:
    """Seed one published KnowledgeItem (NULL org_id — defaulted by conftest)."""
    item = KnowledgeItem(slug=slug, title=title, status="published", type="source")
    session.add(item)
    session.flush()
    version = KnowledgeItemVersion(
        item_id=item.id,
        version_number=1,
        markdown_body=f"# {title}\n\nbody",
        model_id="t",
        created_by="t",
        citations=[],
        status="published",
        title=title,
    )
    session.add(version)
    session.flush()
    item.current_version_id = version.id
    return item


def test_auth_mode_defaults_to_rbac() -> None:
    """``Settings.auth_mode`` defaults to ``"rbac"`` (the cutover)."""
    assert Settings().auth_mode == "rbac"
    # The runtime path (lru_cached) agrees — no env override in the test suite.
    assert get_settings().auth_mode == "rbac"


def test_get_authz_returns_rbac_service_by_default() -> None:
    """The ``get_authz`` swap returns the hierarchical RBAC service under rbac mode."""
    authz = get_authz()
    assert isinstance(authz, HierarchicalRbacAuthorizationService), (
        f"expected HierarchicalRbacAuthorizationService under auth_mode='rbac', "
        f"got {type(authz).__name__}"
    )


def test_default_caller_sees_all_published_items_via_items(api_client, sqlite_factory):
    """A default caller (no X-User-Groups) sees every published item via /items.

    The implicit ``public`` group matches the seeded ``group:public viewer @ org``
    grant, so the RBAC resolver admits the org's published items — the same set
    the legacy group service returned. This is the behavior-preserving cutover
    proof at the HTTP layer, not just the service layer.
    """
    with sqlite_factory() as s:
        _publish(s, "cutover-public", "Cutover Public")
        _publish(s, "cutover-other", "Cutover Other")
        s.commit()

    slugs = {i["slug"] for i in api_client.get("/items").json()}
    assert {"cutover-public", "cutover-other"} <= slugs, (
        f"default caller should see all public items under rbac, got {slugs}"
    )
