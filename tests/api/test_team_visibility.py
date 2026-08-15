"""Visibility verification matrix (Task 4 — M3 Step B).

Proves that a members-only team Space admits members and excludes non-members,
that removing a member cuts access per-request, and that the derived
most-restrictive rule holds across the team boundary. Per the spec, a `members`
Space has NO org-wide viewer grant — only the team-group grant admits members,
so access is governed entirely by grants (the `visibility` column is advisory).

Uses a dedicated org (_TEAM_ORG_ID, distinct from the conftest's _TEST_ORG_ID)
so the conftest's before_flush auto-seed of `group:public viewer @ _TEST_ORG_ID`
does NOT fire — keeping the matrix exact (non-members see nothing).

No new production code is expected beyond Task 2: get_principal_with_teams
injects team:{slug} into the principal, and the existing RBAC resolver matches
the team-group grant. This file verifies that wiring end-to-end.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from k7e_api.auth import Principal, get_authz
from k7e_api.main import app
from k7e_api.models import (
    KnowledgeItem,
    KnowledgeItemVersion,
    Organization,
    RoleGrant,
)
from k7e_api.rbac import HierarchicalRbacAuthorizationService
from k7e_api.teams import provision_team
from k7e_api.tenancy import TenantContext, get_tenant_context
from sqlalchemy import select
from sqlalchemy.orm import Session

_TEAM_ORG_ID = uuid.UUID("00000000-0000-0000-0000-0000000000e1")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _publish(
    session: Session,
    *,
    slug: str,
    title: str,
    org_id: uuid.UUID,
    space_id: uuid.UUID,
    item_type: str = "source",
    allowed_groups: list[str] | None = None,
    source_pages: list[str] | None = None,
) -> KnowledgeItem:
    item = KnowledgeItem(
        org_id=org_id,
        space_id=space_id,
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


@pytest.fixture()
def team_db(sqlite_factory):
    """Seed org + team (members-only space) + one published item.

    Returns the factory (for direct-DB manipulations in tests). Uses
    _TEAM_ORG_ID (≠ _TEST_ORG_ID) so the conftest auto-seed does not fire.
    """
    with sqlite_factory() as s:
        s.add(Organization(id=_TEAM_ORG_ID, slug="team-org", name="Team Org"))
        s.flush()
        team = provision_team(
            s, slug="eng", name="Engineering", owner_id="alice", org_id=_TEAM_ORG_ID
        )
        s.flush()
        _publish(
            s,
            slug="team-src",
            title="Team Source",
            org_id=_TEAM_ORG_ID,
            space_id=team.space_id,
        )
        s.commit()
    return sqlite_factory


@pytest.fixture()
def team_client(api_client, team_db, sqlite_factory):
    """api_client with tenant → team org + authz → RBAC bound to test DB.

    The authz override is needed for the member-management endpoints (can_admin
    opens its own session via the factory). /items reads use the request
    session directly (allowed_item_ids) and would work without it, but the
    removal test exercises DELETE /teams/.../members which needs can_admin.
    """
    app.dependency_overrides[get_tenant_context] = lambda: TenantContext(org_id=_TEAM_ORG_ID)
    app.dependency_overrides[get_authz] = lambda: HierarchicalRbacAuthorizationService(
        session_factory=sqlite_factory
    )
    yield api_client
    app.dependency_overrides.pop(get_tenant_context, None)
    app.dependency_overrides.pop(get_authz, None)


# ---------------------------------------------------------------------------
# (a) member sees team items via /items ; (b) non-member sees none.
# ---------------------------------------------------------------------------


class TestMemberVisibility:
    def test_member_sees_team_item(self, team_client):
        resp = team_client.get("/items", headers={"X-User-Id": "alice"})
        assert resp.status_code == 200, resp.text
        slugs = {i["slug"] for i in resp.json()}
        assert "team-src" in slugs, f"member should see team item: {slugs}"

    def test_non_member_sees_no_team_items(self, team_client):
        resp = team_client.get("/items", headers={"X-User-Id": "nobody"})
        assert resp.status_code == 200, resp.text
        slugs = {i["slug"] for i in resp.json()}
        assert "team-src" not in slugs, f"non-member must not see team item: {slugs}"


# ---------------------------------------------------------------------------
# (c) removing a member cuts access per-request (no cached grant).
# ---------------------------------------------------------------------------


class TestRemovalCutsAccess:
    def test_membership_removal_cuts_access_immediately(self, team_client, team_db):
        # Alice (owner) adds bob as a member.
        team_client.post(
            "/teams/eng/members",
            json={"user_id": "bob", "role": "member"},
            headers={"X-User-Id": "alice"},
        )
        # Bob sees the team item.
        resp = team_client.get("/items", headers={"X-User-Id": "bob"})
        assert "team-src" in {i["slug"] for i in resp.json()}, "bob (member) should see team item"
        # Alice removes bob.
        team_client.delete("/teams/eng/members/bob", headers={"X-User-Id": "alice"})
        # Next request: bob sees nothing.
        resp = team_client.get("/items", headers={"X-User-Id": "bob"})
        assert "team-src" not in {i["slug"] for i in resp.json()}, (
            "removing membership must cut access on the next request"
        )


# ---------------------------------------------------------------------------
# (d) derived most-restrictive rule across the team boundary (service-level).
# ---------------------------------------------------------------------------


class TestDerivedMostRestrictiveAcrossTeam:
    """A space-viewer (not a team member) sees the public source but not the
    team-restricted source nor a concept derived from both; a member sees all.

    This proves the derived most-restrictive rule (carried from the
    permission-aware feature) holds across the team boundary: a concept whose
    provenance references a team-restricted source is hidden from a non-member
    even though they can read the concept's space.
    """

    def test_space_viewer_sees_public_not_restricted_nor_concept(self, sqlite_factory):
        with sqlite_factory() as s:
            s.add(Organization(id=_TEAM_ORG_ID, slug="team-org", name="Team Org"))
            s.flush()
            team = provision_team(
                s,
                slug="eng",
                name="Engineering",
                owner_id="alice",
                org_id=_TEAM_ORG_ID,
            )
            s.flush()
            space_id = team.space_id
            _publish(
                s,
                slug="pub-src",
                title="Public",
                org_id=_TEAM_ORG_ID,
                space_id=space_id,
            )
            _publish(
                s,
                slug="team-secret-src",
                title="Team Secret",
                org_id=_TEAM_ORG_ID,
                space_id=space_id,
                allowed_groups=["team:eng"],
            )
            _publish(
                s,
                slug="concept",
                title="Concept",
                org_id=_TEAM_ORG_ID,
                space_id=space_id,
                item_type="concept",
                source_pages=["pub-src", "team-secret-src"],
            )
            # A space-viewer grant for bob (NOT in team:eng group).
            s.add(
                RoleGrant(
                    principal_kind="user",
                    principal_id="bob",
                    role="viewer",
                    scope_kind="space",
                    scope_id=space_id,
                )
            )
            s.commit()

        service = HierarchicalRbacAuthorizationService()
        member = Principal(user_id="alice", roles=[], groups=["team:eng"])
        non_member_viewer = Principal(user_id="bob", roles=[], groups=[])

        def _slugs(p: Principal) -> set[str]:
            with sqlite_factory() as s:
                ids = service.allowed_item_ids(p, s)
                if not ids:
                    return set()
                return {
                    r[0]
                    for r in s.execute(
                        select(KnowledgeItem.slug).where(KnowledgeItem.id.in_(ids))
                    ).all()
                }

        # Member (team:eng group → editor grant) sees all three.
        assert _slugs(member) == {"pub-src", "team-secret-src", "concept"}
        # Non-member space-viewer sees only the public source: the restricted
        # source is hidden by allowed_groups, and the concept is hidden by the
        # derived most-restrictive rule (it references the restricted source).
        assert _slugs(non_member_viewer) == {"pub-src"}
