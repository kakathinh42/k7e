"""M0 hardening — lock the "empty ``provenance.source_pages`` → public" semantics.

A derived page (``type != "source"``) with empty/absent ``source_pages`` is
visible to all callers: ``all(sp in visible for sp in []) == True`` (vacuous
truth). This is the intended MVP behavior (a derived page synthesised from no
restricted sources is public). These tests lock it for BOTH authorization
services so a future refactor can't silently change it.
"""

from __future__ import annotations

from k7e_api.auth import GroupAuthorizationService, Principal
from k7e_api.models import KnowledgeItem, KnowledgeItemVersion
from k7e_api.rbac import HierarchicalRbacAuthorizationService


def _publish_derived(session, slug: str, provenance) -> KnowledgeItem:
    """Seed a published derived (concept) page with the given provenance."""
    item = KnowledgeItem(
        slug=slug,
        title=slug,
        status="published",
        type="concept",
        provenance=provenance,
    )
    session.add(item)
    session.flush()
    version = KnowledgeItemVersion(
        item_id=item.id,
        version_number=1,
        status="published",
        markdown_body="body",
        model_id="test-model",
        created_by="tester",
    )
    session.add(version)
    session.flush()
    item.current_version_id = version.id
    session.commit()
    return item


def test_group_auth_derived_empty_source_pages_is_public(sqlite_factory):
    session = sqlite_factory()
    empty = _publish_derived(session, "concept-empty-list", {"source_pages": []})
    none_prov = _publish_derived(session, "concept-no-prov", None)

    svc = GroupAuthorizationService()
    # A caller in no groups (implicit "public" only).
    allowed = svc.allowed_item_ids(Principal(user_id="u", roles=[], groups=[]), session)

    assert empty.id in allowed, "derived page with source_pages=[] must be public"
    assert none_prov.id in allowed, "derived page with provenance=None must be public"


def test_rbac_derived_empty_source_pages_is_public(sqlite_factory):
    session = sqlite_factory()
    # The conftest before_flush hook stamps org_id=<test org> on these items and
    # seeds the group:public viewer grant, so a public caller's grant admits them
    # by scope; the empty-source_pages rule then keeps them visible.
    empty = _publish_derived(session, "concept-empty-list", {"source_pages": []})
    none_prov = _publish_derived(session, "concept-no-prov", None)

    svc = HierarchicalRbacAuthorizationService(session_factory=sqlite_factory)
    allowed = svc.allowed_item_ids(Principal(user_id="u", roles=[], groups=[]), session)

    assert empty.id in allowed, "derived page with source_pages=[] must be public"
    assert none_prov.id in allowed, "derived page with provenance=None must be public"
