"""Hierarchical RBAC inheritance truth-table (Task 3 — M2).

Exercises ``HierarchicalRbacAuthorizationService`` directly against a seeded
org/space/project hierarchy + role grants, asserting the full read matrix from
the spec Testing Strategy (§3 6-step resolver), plus the ``can_write`` /
``can_review`` grant + ``X-User-Roles`` semantics.

Read matrix (all 9 cases)
-------------------------
1. Org ``viewer`` grant (the seeded ``group:public`` shape) → reads every item
   in the org (the behavior-preserving baseline).
2. Space ``viewer`` grant → reads that space + its projects, NOT sibling spaces.
3. Project ``viewer`` grant → reads only that project.
4. User grant vs group grant → both resolve.
5. ``editor``/``reviewer``/``admin`` imply ``viewer`` read (read-implied).
6. ``allowed_groups`` override subtracts (finance page hidden from non-finance,
   visible to finance).
7. Derived most-restrictive (a concept over a restricted source is hidden from
   non-finance; an unresolvable source slug hides the page — fail-safe).
8. No grant → empty set (fail-closed).
9. ``app`` principal grant → admits nothing (inert in M2).

The service is constructed with the test's ``sqlite_factory`` as its session
factory so the write/review grant checks read the same in-memory DB the read
path is seeded against (the Protocol gives ``can_write``/``can_review`` no
session of their own).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from k7e_api.auth import Principal
from k7e_api.models import (
    KnowledgeItem,
    KnowledgeItemVersion,
    Organization,
    Project,
    RoleGrant,
    Space,
)
from k7e_api.rbac import HierarchicalRbacAuthorizationService, Scope
from sqlalchemy import select
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Deterministic ids so the assertions below are self-documenting.
# ---------------------------------------------------------------------------

_ORG_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
_SPACE_ENG_ID = uuid.UUID("00000000-0000-0000-0000-0000000000b1")
_SPACE_FIN_ID = uuid.UUID("00000000-0000-0000-0000-0000000000b2")
_PROJ_ENG_CORE_ID = uuid.UUID("00000000-0000-0000-0000-0000000000c1")
_PROJ_FIN_RPT_ID = uuid.UUID("00000000-0000-0000-0000-0000000000c2")

# Published source/derived slugs seeded by _seed_hierarchy. Each case below
# asserts a subset of these.
_ALL_SLUGS = {
    "eng-space-src",
    "eng-core-src",
    "fin-space-src",
    "fin-rpt-src",
    "fin-secret-src",
    "eng-public-src",
    "concept-from-public",
    "concept-from-secret",
    "concept-ghost",
}

# Org-level viewer (non-finance) sees every public source + the purely-public
# derived concept; the finance source, the finance-derived concept, and the
# ghost-derived concept are hidden. This is the behavior-preserving baseline —
# the same set GroupAuthorizationService yields for a public caller.
_ORG_VIEWER_PUBLIC = {
    "eng-space-src",
    "eng-core-src",
    "fin-space-src",
    "fin-rpt-src",
    "eng-public-src",
    "concept-from-public",
}


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _publish(
    session: Session,
    *,
    slug: str,
    title: str,
    org_id: uuid.UUID,
    space_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    item_type: str = "source",
    allowed_groups: list[str] | None = None,
    source_pages: list[str] | None = None,
) -> KnowledgeItem:
    """Seed a published KnowledgeItem + version at a containment level."""
    item = KnowledgeItem(
        org_id=org_id,
        space_id=space_id,
        project_id=project_id,
        slug=slug,
        title=title,
        status="published",
        type=item_type,
        allowed_groups=allowed_groups,
        provenance={"resource": None, "source_pages": source_pages or []},
        created_at=_now(),
        updated_at=_now(),
    )
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
        created_at=_now(),
    )
    session.add(version)
    session.flush()
    item.current_version_id = version.id
    return item


def _seed_hierarchy(session: Session) -> None:
    """Seed one org, two spaces, two projects, and the published item set."""
    session.add(Organization(id=_ORG_ID, slug="test-org", name="Test Org"))
    session.add_all(
        [
            Space(id=_SPACE_ENG_ID, org_id=_ORG_ID, slug="eng", name="Engineering"),
            Space(id=_SPACE_FIN_ID, org_id=_ORG_ID, slug="fin", name="Finance"),
        ]
    )
    session.add_all(
        [
            Project(
                id=_PROJ_ENG_CORE_ID,
                space_id=_SPACE_ENG_ID,
                slug="core",
                name="Core",
            ),
            Project(
                id=_PROJ_FIN_RPT_ID,
                space_id=_SPACE_FIN_ID,
                slug="rpt",
                name="Reports",
            ),
        ]
    )
    session.flush()

    # Public sources at each containment level.
    _publish(
        session,
        slug="eng-space-src",
        title="Eng Space Src",
        org_id=_ORG_ID,
        space_id=_SPACE_ENG_ID,
    )
    _publish(
        session,
        slug="eng-core-src",
        title="Eng Core Src",
        org_id=_ORG_ID,
        space_id=_SPACE_ENG_ID,
        project_id=_PROJ_ENG_CORE_ID,
    )
    _publish(
        session,
        slug="fin-space-src",
        title="Fin Space Src",
        org_id=_ORG_ID,
        space_id=_SPACE_FIN_ID,
    )
    _publish(
        session,
        slug="fin-rpt-src",
        title="Fin Rpt Src",
        org_id=_ORG_ID,
        space_id=_SPACE_FIN_ID,
        project_id=_PROJ_FIN_RPT_ID,
    )
    # Finance-restricted source (allowed_groups subtracts).
    _publish(
        session,
        slug="fin-secret-src",
        title="Fin Secret Src",
        org_id=_ORG_ID,
        space_id=_SPACE_FIN_ID,
        allowed_groups=["finance"],
    )
    # Public source used as a derived page's provenance.
    _publish(
        session,
        slug="eng-public-src",
        title="Eng Public Src",
        org_id=_ORG_ID,
        space_id=_SPACE_ENG_ID,
    )
    # Derived pages.
    _publish(
        session,
        slug="concept-from-public",
        title="Concept From Public",
        org_id=_ORG_ID,
        space_id=_SPACE_ENG_ID,
        item_type="concept",
        source_pages=["eng-public-src"],
    )
    _publish(
        session,
        slug="concept-from-secret",
        title="Concept From Secret",
        org_id=_ORG_ID,
        space_id=_SPACE_ENG_ID,
        item_type="concept",
        source_pages=["eng-public-src", "fin-secret-src"],
    )
    # Derived page with an unresolvable source slug → fail-safe hidden.
    _publish(
        session,
        slug="concept-ghost",
        title="Concept Ghost",
        org_id=_ORG_ID,
        space_id=_SPACE_ENG_ID,
        item_type="concept",
        source_pages=["nonexistent-src"],
    )
    session.commit()


def _grant(
    session: Session,
    *,
    principal_kind: str,
    principal_id: str,
    role: str,
    scope_kind: str,
    scope_id: uuid.UUID,
) -> None:
    """Seed a RoleGrant and commit."""
    session.add(
        RoleGrant(
            principal_kind=principal_kind,
            principal_id=principal_id,
            role=role,
            scope_kind=scope_kind,
            scope_id=scope_id,
        )
    )
    session.commit()


def _slugs_for(session: Session, ids: set[uuid.UUID]) -> set[str]:
    """Map an allowed-item-id set back to slugs for readable assertions."""
    if not ids:
        return set()
    rows = session.execute(select(KnowledgeItem.slug).where(KnowledgeItem.id.in_(ids))).all()
    return {row[0] for row in rows}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def seeded_factory(sqlite_factory):
    """Seed the hierarchy into the in-memory DB and return the session factory.

    Grants are NOT seeded here — each test adds exactly the grants it exercises
    so the truth-table cases stay independent. The returned factory is shared
    (StaticPool) so a grant committed in one session is visible to the next.
    """
    with sqlite_factory() as session:
        _seed_hierarchy(session)
    return sqlite_factory


def _allowed_slugs(
    service: HierarchicalRbacAuthorizationService,
    principal: Principal,
    session: Session,
) -> set[str]:
    return _slugs_for(session, service.allowed_item_ids(principal, session))


# ---------------------------------------------------------------------------
# Read path — the 9-case truth table
# ---------------------------------------------------------------------------


class TestOrgViewerGrant:
    """Case 1: an org-level viewer grant reads every item in the org."""

    def test_org_viewer_reads_all_public_items(self, seeded_factory):
        with seeded_factory() as s:
            _grant(
                s,
                principal_kind="group",
                principal_id="public",
                role="viewer",
                scope_kind="org",
                scope_id=_ORG_ID,
            )

        service = HierarchicalRbacAuthorizationService()
        principal = Principal(user_id="alice", roles=[], groups=[])
        with seeded_factory() as s:
            slugs = _allowed_slugs(service, principal, s)

        assert slugs == _ORG_VIEWER_PUBLIC, (
            f"org viewer (group:public) should see exactly the public baseline: got {slugs}"
        )
        # Explicitly: the finance source + finance-derived concept + ghost are
        # NOT visible to a non-finance caller.
        assert "fin-secret-src" not in slugs
        assert "concept-from-secret" not in slugs
        assert "concept-ghost" not in slugs


class TestSpaceViewerGrant:
    """Case 2: a space viewer grant reads that space + its projects, not siblings."""

    def test_space_viewer_admits_space_and_projects_not_siblings(self, seeded_factory):
        with seeded_factory() as s:
            _grant(
                s,
                principal_kind="user",
                principal_id="alice",
                role="viewer",
                scope_kind="space",
                scope_id=_SPACE_ENG_ID,
            )

        service = HierarchicalRbacAuthorizationService()
        principal = Principal(user_id="alice", roles=[], groups=[])
        with seeded_factory() as s:
            slugs = _allowed_slugs(service, principal, s)

        # eng space item + eng project item + the public source + its derived
        # concept all live in the eng space.
        assert slugs == {
            "eng-space-src",
            "eng-core-src",
            "eng-public-src",
            "concept-from-public",
        }, f"space viewer should see only its space's items: got {slugs}"
        # Sibling finance space is invisible.
        assert "fin-space-src" not in slugs
        assert "fin-rpt-src" not in slugs
        assert "fin-secret-src" not in slugs
        # concept-from-secret is in eng space but references a finance source —
        # hidden by the derived most-restrictive rule.
        assert "concept-from-secret" not in slugs


class TestProjectViewerGrant:
    """Case 3: a project viewer grant reads only that project."""

    def test_project_viewer_admits_only_that_project(self, seeded_factory):
        with seeded_factory() as s:
            _grant(
                s,
                principal_kind="user",
                principal_id="alice",
                role="viewer",
                scope_kind="project",
                scope_id=_PROJ_ENG_CORE_ID,
            )

        service = HierarchicalRbacAuthorizationService()
        principal = Principal(user_id="alice", roles=[], groups=[])
        with seeded_factory() as s:
            slugs = _allowed_slugs(service, principal, s)

        assert slugs == {"eng-core-src"}, (
            f"project viewer should see only that project's item: got {slugs}"
        )
        # Same-space but different-containment items are NOT admitted.
        assert "eng-space-src" not in slugs


class TestUserVsGroupGrant:
    """Case 4: a user grant and a group grant both resolve for the same caller.

    Each arm uses a fresh in-memory DB seeded with exactly one grant, so the
    two grant kinds are exercised independently (the shared StaticPool would
    otherwise let them coexist).
    """

    def test_user_grant_resolves(self, sqlite_factory):
        with sqlite_factory() as s:
            _seed_hierarchy(s)
            _grant(
                s,
                principal_kind="user",
                principal_id="alice",
                role="viewer",
                scope_kind="space",
                scope_id=_SPACE_ENG_ID,
            )

        service = HierarchicalRbacAuthorizationService()
        principal = Principal(user_id="alice", roles=[], groups=[])
        with sqlite_factory() as s:
            slugs = _allowed_slugs(service, principal, s)
        assert slugs == {
            "eng-space-src",
            "eng-core-src",
            "eng-public-src",
            "concept-from-public",
        }

    def test_group_grant_resolves_for_member(self, sqlite_factory):
        with sqlite_factory() as s:
            _seed_hierarchy(s)
            _grant(
                s,
                principal_kind="group",
                principal_id="eng",
                role="viewer",
                scope_kind="space",
                scope_id=_SPACE_ENG_ID,
            )

        service = HierarchicalRbacAuthorizationService()
        principal = Principal(user_id="alice", roles=[], groups=["eng"])
        with sqlite_factory() as s:
            slugs = _allowed_slugs(service, principal, s)
        assert slugs == {
            "eng-space-src",
            "eng-core-src",
            "eng-public-src",
            "concept-from-public",
        }


class TestRolesImplyViewerRead:
    """Case 5: editor/reviewer/admin grants confer the same read as viewer."""

    @pytest.mark.parametrize("role", ["editor", "reviewer", "admin"])
    def test_higher_roles_imply_viewer_read(self, seeded_factory, role):
        with seeded_factory() as s:
            _grant(
                s,
                principal_kind="user",
                principal_id="alice",
                role=role,
                scope_kind="org",
                scope_id=_ORG_ID,
            )

        service = HierarchicalRbacAuthorizationService()
        principal = Principal(user_id="alice", roles=[], groups=[])
        with seeded_factory() as s:
            slugs = _allowed_slugs(service, principal, s)

        assert slugs == _ORG_VIEWER_PUBLIC, (
            f"{role} grant should admit the same read as viewer: got {slugs}"
        )


class TestAllowedGroupsSubtracts:
    """Case 6: allowed_groups subtracts a page below an otherwise-readable scope."""

    def test_finance_page_hidden_from_non_finance_org_viewer(self, seeded_factory):
        with seeded_factory() as s:
            _grant(
                s,
                principal_kind="group",
                principal_id="public",
                role="viewer",
                scope_kind="org",
                scope_id=_ORG_ID,
            )

        service = HierarchicalRbacAuthorizationService()
        non_finance = Principal(user_id="alice", roles=[], groups=[])
        with seeded_factory() as s:
            assert "fin-secret-src" not in _allowed_slugs(service, non_finance, s)

    def test_finance_page_visible_to_finance_org_viewer(self, seeded_factory):
        with seeded_factory() as s:
            _grant(
                s,
                principal_kind="group",
                principal_id="public",
                role="viewer",
                scope_kind="org",
                scope_id=_ORG_ID,
            )

        service = HierarchicalRbacAuthorizationService()
        finance = Principal(user_id="alice", roles=[], groups=["finance"])
        with seeded_factory() as s:
            slugs = _allowed_slugs(service, finance, s)
        assert "fin-secret-src" in slugs


class TestDerivedMostRestrictive:
    """Case 7: a derived page survives iff every source slug is visible."""

    def test_concept_over_restricted_source_hidden_from_non_finance(self, seeded_factory):
        with seeded_factory() as s:
            _grant(
                s,
                principal_kind="group",
                principal_id="public",
                role="viewer",
                scope_kind="org",
                scope_id=_ORG_ID,
            )

        service = HierarchicalRbacAuthorizationService()
        non_finance = Principal(user_id="alice", roles=[], groups=[])
        with seeded_factory() as s:
            slugs = _allowed_slugs(service, non_finance, s)
        assert "concept-from-secret" not in slugs
        assert "concept-ghost" not in slugs

    def test_concept_over_restricted_source_visible_to_finance(self, seeded_factory):
        with seeded_factory() as s:
            _grant(
                s,
                principal_kind="group",
                principal_id="public",
                role="viewer",
                scope_kind="org",
                scope_id=_ORG_ID,
            )

        service = HierarchicalRbacAuthorizationService()
        finance = Principal(user_id="alice", roles=[], groups=["finance"])
        with seeded_factory() as s:
            slugs = _allowed_slugs(service, finance, s)
        assert "concept-from-secret" in slugs
        # The ghost concept is still hidden — no source resolves.
        assert "concept-ghost" not in slugs

    def test_unresolvable_source_hides_derived_page(self, sqlite_factory):
        """A derived page whose source slug does not resolve is hidden (fail-safe)."""
        with sqlite_factory() as s:
            _seed_hierarchy(s)
            _grant(
                s,
                principal_kind="group",
                principal_id="public",
                role="viewer",
                scope_kind="org",
                scope_id=_ORG_ID,
            )

        service = HierarchicalRbacAuthorizationService()
        finance = Principal(user_id="alice", roles=[], groups=["finance"])
        with sqlite_factory() as s:
            slugs = _allowed_slugs(service, finance, s)
        assert "concept-ghost" not in slugs


class TestNoGrantFailsClosed:
    """Case 8: a caller matching no grant gets an empty set (fail-closed)."""

    def test_no_grant_yields_empty_set(self, seeded_factory):
        service = HierarchicalRbacAuthorizationService()
        # No grant seeded (the seeded_factory fixture seeds no grants). The
        # caller is not in any group that has a grant.
        principal = Principal(user_id="nobody", roles=[], groups=[])
        with seeded_factory() as s:
            allowed = service.allowed_item_ids(principal, s)
        assert allowed == set(), (
            f"a caller with no matching grant must get an empty set, got {allowed}"
        )


class TestAppPrincipalIsInert:
    """Case 9: an `app` principal grant admits nothing in M2 (schema-ready only)."""

    def test_app_grant_admits_nothing(self, seeded_factory):
        with seeded_factory() as s:
            _grant(
                s,
                principal_kind="app",
                principal_id="myapp",
                role="admin",
                scope_kind="org",
                scope_id=_ORG_ID,
            )

        service = HierarchicalRbacAuthorizationService()
        principal = Principal(user_id="alice", roles=[], groups=[])
        with seeded_factory() as s:
            allowed = service.allowed_item_ids(principal, s)
        assert allowed == set(), (
            f"app principal grants are inert in M2 — must admit nothing: got {allowed}"
        )


# ---------------------------------------------------------------------------
# Write / review path — grants + X-User-Roles back-compat
# ---------------------------------------------------------------------------


class TestCanReviewAndCanWrite:
    """``can_write``/``can_review`` honour grants (role ≥ editor/reviewer at a
    covering scope) OR the ``X-User-Roles`` header (back-compat)."""

    # -- X-User-Roles back-compat (no grants needed) --------------------

    def test_reviewer_header_passes_review_and_write(self, seeded_factory):
        service = HierarchicalRbacAuthorizationService(session_factory=seeded_factory)
        principal = Principal(user_id="alice", roles=["reviewer"], groups=[])
        assert service.can_review(principal) is True
        # reviewer implies editor for the write path.
        assert service.can_write(principal) is True

    def test_editor_header_passes_write_not_review(self, seeded_factory):
        service = HierarchicalRbacAuthorizationService(session_factory=seeded_factory)
        principal = Principal(user_id="alice", roles=["editor"], groups=[])
        assert service.can_write(principal) is True
        assert service.can_review(principal) is False

    def test_admin_header_passes_write_not_review(self, seeded_factory):
        # The can_review header back-compat is reviewer-only (it preserves the
        # pre-RBAC can_review exactly); admin reaches review via a grant, not
        # via the header. can_write's back-compat does include admin.
        service = HierarchicalRbacAuthorizationService(session_factory=seeded_factory)
        principal = Principal(user_id="alice", roles=["admin"], groups=[])
        assert service.can_write(principal) is True
        assert service.can_review(principal) is False

    def test_viewer_header_passes_neither(self, seeded_factory):
        service = HierarchicalRbacAuthorizationService(session_factory=seeded_factory)
        principal = Principal(user_id="alice", roles=["viewer"], groups=[])
        assert service.can_review(principal) is False
        assert service.can_write(principal) is False

    def test_dev_user_passes_review_and_write(self, seeded_factory):
        service = HierarchicalRbacAuthorizationService(session_factory=seeded_factory)
        principal = Principal(user_id="dev", roles=[], groups=[])
        assert service.can_review(principal) is True
        assert service.can_write(principal) is True

    def test_no_role_no_grant_denies_both(self, seeded_factory):
        service = HierarchicalRbacAuthorizationService(session_factory=seeded_factory)
        principal = Principal(user_id="alice", roles=[], groups=[])
        assert service.can_review(principal) is False
        assert service.can_write(principal) is False

    # -- Grant-based (header roles empty — exercises the grant path) -----

    def test_reviewer_grant_at_org_passes_review_any_scope(self, seeded_factory):
        with seeded_factory() as s:
            _grant(
                s,
                principal_kind="user",
                principal_id="alice",
                role="reviewer",
                scope_kind="org",
                scope_id=_ORG_ID,
            )

        service = HierarchicalRbacAuthorizationService(session_factory=seeded_factory)
        principal = Principal(user_id="alice", roles=[], groups=[])
        # scope=None → "reviewer at any scope".
        assert service.can_review(principal) is True
        # reviewer implies editor for write.
        assert service.can_write(principal) is True
        # Org reviewer covers a space scope (downward inheritance).
        assert service.can_review(principal, Scope("space", _SPACE_ENG_ID)) is True
        assert service.can_review(principal, Scope("space", _SPACE_FIN_ID)) is True

    def test_editor_grant_at_space_passes_write_not_review(self, seeded_factory):
        with seeded_factory() as s:
            _grant(
                s,
                principal_kind="user",
                principal_id="alice",
                role="editor",
                scope_kind="space",
                scope_id=_SPACE_ENG_ID,
            )

        service = HierarchicalRbacAuthorizationService(session_factory=seeded_factory)
        principal = Principal(user_id="alice", roles=[], groups=[])
        assert service.can_write(principal) is True
        # editor < reviewer → cannot review.
        assert service.can_review(principal) is False
        # Covers the eng space itself.
        assert service.can_write(principal, Scope("space", _SPACE_ENG_ID)) is True
        # Covers a project inside the eng space.
        assert service.can_write(principal, Scope("project", _PROJ_ENG_CORE_ID)) is True

    def test_space_grant_does_not_cover_sibling_space(self, seeded_factory):
        """Scope specificity: an eng-space editor grant does NOT cover the fin space."""
        with seeded_factory() as s:
            _grant(
                s,
                principal_kind="user",
                principal_id="alice",
                role="editor",
                scope_kind="space",
                scope_id=_SPACE_ENG_ID,
            )

        service = HierarchicalRbacAuthorizationService(session_factory=seeded_factory)
        principal = Principal(user_id="alice", roles=[], groups=[])
        assert service.can_write(principal, Scope("space", _SPACE_FIN_ID)) is False
        # An org-level reviewer DOES cover the fin space (downward).
        with seeded_factory() as s:
            _grant(
                s,
                principal_kind="user",
                principal_id="bob",
                role="reviewer",
                scope_kind="org",
                scope_id=_ORG_ID,
            )
        org_reviewer = Principal(user_id="bob", roles=[], groups=[])
        assert service.can_review(org_reviewer, Scope("space", _SPACE_FIN_ID)) is True

    def test_viewer_grant_denies_write_and_review(self, seeded_factory):
        with seeded_factory() as s:
            _grant(
                s,
                principal_kind="user",
                principal_id="alice",
                role="viewer",
                scope_kind="org",
                scope_id=_ORG_ID,
            )

        service = HierarchicalRbacAuthorizationService(session_factory=seeded_factory)
        principal = Principal(user_id="alice", roles=[], groups=[])
        assert service.can_write(principal) is False
        assert service.can_review(principal) is False

    def test_admin_grant_passes_review_and_write(self, seeded_factory):
        # An admin grant (role ≥ reviewer and ≥ editor) reaches both gates via
        # the grant path — complementing the header test where admin-via-header
        # alone cannot review (the can_review back-compat is reviewer-only).
        with seeded_factory() as s:
            _grant(
                s,
                principal_kind="user",
                principal_id="alice",
                role="admin",
                scope_kind="space",
                scope_id=_SPACE_ENG_ID,
            )

        service = HierarchicalRbacAuthorizationService(session_factory=seeded_factory)
        principal = Principal(user_id="alice", roles=[], groups=[])
        assert service.can_review(principal) is True
        assert service.can_write(principal) is True
        assert service.can_review(principal, Scope("project", _PROJ_ENG_CORE_ID)) is True
        # The admin grant is on the eng space — it does not cover the fin space.
        assert service.can_review(principal, Scope("space", _SPACE_FIN_ID)) is False
