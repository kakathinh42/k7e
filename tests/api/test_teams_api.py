"""Teams REST API (Task 3 — M3 Step A).

POST   /teams                       — any authenticated caller → owner.
GET    /teams/{slug}                 — member-gated (hide existence from non-members).
POST   /teams/{slug}/members         — owner/admin (can_admin) adds a member.
DELETE /teams/{slug}/members/{user_id} — owner/admin removes a member.

Member-management endpoints exercise can_admin via the owner's user admin grant
(created by provision_team), so they use the gated_client fixture (RBAC service
bound to the test DB; the default get_authz opens SessionLocal and can't see
test-seeded grants). Header back-compat is unaffected (can_admin checks
X-User-Roles before walking grants).
"""

from __future__ import annotations

import pytest
from k7e_api.auth import get_authz
from k7e_api.main import app
from k7e_api.models import Membership, Organization, RoleGrant
from k7e_api.rbac import HierarchicalRbacAuthorizationService
from sqlalchemy import select

from tests.api.conftest import TEST_TENANT_CONTEXT

_ORG_ID = TEST_TENANT_CONTEXT.org_id  # the api_client's tenant org


@pytest.fixture()
def seeded_org(sqlite_factory):
    """The tenant org must exist for the team's FK."""
    with sqlite_factory() as s:
        s.add(Organization(id=_ORG_ID, slug="test-org", name="Test Org"))
        s.commit()


@pytest.fixture()
def gated_client(api_client, sqlite_factory):
    """api_client + get_authz → RBAC service bound to the test DB."""
    app.dependency_overrides[get_authz] = lambda: HierarchicalRbacAuthorizationService(
        session_factory=sqlite_factory
    )
    yield api_client
    app.dependency_overrides.pop(get_authz, None)


# Non-privileged sentinel role — not in {editor,reviewer,admin,viewer}, so it
# never short-circuits can_admin/can_write/can_review (exercises grants).
_NO_ROLE = {"X-User-Roles": "reader"}


class TestCreateTeam:
    def test_create_team_makes_caller_owner(self, gated_client, seeded_org):
        resp = gated_client.post(
            "/teams",
            json={"slug": "eng", "name": "Engineering"},
            headers={"X-User-Id": "alice", **_NO_ROLE},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["slug"] == "eng"
        assert body["name"] == "Engineering"
        assert body["created_by"] == "alice"
        roles = {m["user_id"]: m["role"] for m in body["members"]}
        assert roles == {"alice": "owner"}

    def test_duplicate_slug_returns_409(self, gated_client, seeded_org):
        r1 = gated_client.post(
            "/teams",
            json={"slug": "eng", "name": "Engineering"},
            headers={"X-User-Id": "alice", **_NO_ROLE},
        )
        assert r1.status_code == 201, r1.text
        r2 = gated_client.post(
            "/teams",
            json={"slug": "eng", "name": "Eng Two"},
            headers={"X-User-Id": "alice", **_NO_ROLE},
        )
        assert r2.status_code == 409, r2.text

    def test_reserved_personal_slug_returns_400(self, gated_client, seeded_org):
        resp = gated_client.post(
            "/teams",
            json={"slug": "personal", "name": "X"},
            headers={"X-User-Id": "alice", **_NO_ROLE},
        )
        assert resp.status_code == 400, resp.text


class TestGetTeam:
    def test_member_sees_team(self, gated_client, seeded_org):
        gated_client.post(
            "/teams",
            json={"slug": "eng", "name": "Engineering"},
            headers={"X-User-Id": "alice", **_NO_ROLE},
        )
        resp = gated_client.get("/teams/eng", headers={"X-User-Id": "alice", **_NO_ROLE})
        assert resp.status_code == 200, resp.text
        assert resp.json()["slug"] == "eng"

    def test_non_member_gets_404(self, gated_client, seeded_org):
        gated_client.post(
            "/teams",
            json={"slug": "eng", "name": "Engineering"},
            headers={"X-User-Id": "alice", **_NO_ROLE},
        )
        resp = gated_client.get("/teams/eng", headers={"X-User-Id": "nobody", **_NO_ROLE})
        assert resp.status_code == 404, resp.text


class TestMemberManagement:
    def test_owner_adds_member(self, gated_client, seeded_org):
        gated_client.post(
            "/teams",
            json={"slug": "eng", "name": "Engineering"},
            headers={"X-User-Id": "alice", **_NO_ROLE},
        )
        resp = gated_client.post(
            "/teams/eng/members",
            json={"user_id": "bob", "role": "member"},
            headers={"X-User-Id": "alice", **_NO_ROLE},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["user_id"] == "bob"
        assert resp.json()["role"] == "member"

    def test_non_admin_member_denied_403(self, gated_client, seeded_org):
        gated_client.post(
            "/teams",
            json={"slug": "eng", "name": "Engineering"},
            headers={"X-User-Id": "alice", **_NO_ROLE},
        )
        gated_client.post(
            "/teams/eng/members",
            json={"user_id": "bob", "role": "member"},
            headers={"X-User-Id": "alice", **_NO_ROLE},
        )
        # Bob (member, no admin grant) tries to add carol → 403.
        resp = gated_client.post(
            "/teams/eng/members",
            json={"user_id": "carol", "role": "member"},
            headers={"X-User-Id": "bob", **_NO_ROLE},
        )
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"] == "Admin role required"

    def test_owner_removes_member(self, gated_client, seeded_org, sqlite_factory):
        gated_client.post(
            "/teams",
            json={"slug": "eng", "name": "Engineering"},
            headers={"X-User-Id": "alice", **_NO_ROLE},
        )
        gated_client.post(
            "/teams/eng/members",
            json={"user_id": "bob", "role": "member"},
            headers={"X-User-Id": "alice", **_NO_ROLE},
        )
        resp = gated_client.delete(
            "/teams/eng/members/bob", headers={"X-User-Id": "alice", **_NO_ROLE}
        )
        assert resp.status_code == 204, resp.text
        with sqlite_factory() as s:
            assert s.execute(select(Membership).where(Membership.user_id == "bob")).first() is None

    def test_admin_role_creates_admin_grant(self, gated_client, seeded_org):
        """Adding an 'admin' member seeds a user admin grant so they can_admin."""
        gated_client.post(
            "/teams",
            json={"slug": "eng", "name": "Engineering"},
            headers={"X-User-Id": "alice", **_NO_ROLE},
        )
        gated_client.post(
            "/teams/eng/members",
            json={"user_id": "bob", "role": "admin"},
            headers={"X-User-Id": "alice", **_NO_ROLE},
        )
        # Bob can now add carol (can_admin via his admin grant).
        resp = gated_client.post(
            "/teams/eng/members",
            json={"user_id": "carol", "role": "member"},
            headers={"X-User-Id": "bob", **_NO_ROLE},
        )
        assert resp.status_code == 201, resp.text

    def test_remove_admin_member_also_drops_admin_grant(
        self, gated_client, seeded_org, sqlite_factory
    ):
        """Removing an admin member deletes their user admin grant too."""
        gated_client.post(
            "/teams",
            json={"slug": "eng", "name": "Engineering"},
            headers={"X-User-Id": "alice", **_NO_ROLE},
        )
        gated_client.post(
            "/teams/eng/members",
            json={"user_id": "bob", "role": "admin"},
            headers={"X-User-Id": "alice", **_NO_ROLE},
        )
        gated_client.delete("/teams/eng/members/bob", headers={"X-User-Id": "alice", **_NO_ROLE})
        with sqlite_factory() as s:
            assert (
                s.execute(
                    select(RoleGrant).where(
                        RoleGrant.principal_kind == "user",
                        RoleGrant.principal_id == "bob",
                        RoleGrant.role == "admin",
                    )
                ).first()
                is None
            ), "removing an admin member must drop their user admin grant"


class TestListTeams:
    def test_lists_only_caller_teams(self, gated_client, seeded_org):
        # alice owns "eng"; bob owns "ops".
        gated_client.post(
            "/teams",
            json={"slug": "eng", "name": "Engineering"},
            headers={"X-User-Id": "alice", **_NO_ROLE},
        )
        gated_client.post(
            "/teams",
            json={"slug": "ops", "name": "Ops"},
            headers={"X-User-Id": "bob", **_NO_ROLE},
        )
        resp = gated_client.get("/teams", headers={"X-User-Id": "alice", **_NO_ROLE})
        assert resp.status_code == 200, resp.text
        assert {t["slug"] for t in resp.json()} == {"eng"}

    def test_empty_when_no_memberships(self, gated_client, seeded_org):
        resp = gated_client.get("/teams", headers={"X-User-Id": "nobody", **_NO_ROLE})
        assert resp.status_code == 200, resp.text
        assert resp.json() == []

    def test_excludes_other_org_teams(self, gated_client, seeded_org, sqlite_factory):
        import uuid

        from k7e_api.models import Membership, Organization, Space, Team

        other_org = uuid.uuid4()
        with sqlite_factory() as s:
            s.add(Organization(id=other_org, slug="other-org", name="Other"))
            space = Space(org_id=other_org, slug="foreign", name="Foreign", visibility="members")
            s.add(space)
            s.flush()
            team = Team(
                org_id=other_org,
                space_id=space.id,
                slug="foreign",
                name="Foreign",
                created_by="alice",
            )
            s.add(team)
            s.flush()
            s.add(Membership(team_id=team.id, user_id="alice", role="owner"))
            s.commit()
        # alice IS a member of the foreign-org team, but GET /teams is tenant-scoped.
        resp = gated_client.get("/teams", headers={"X-User-Id": "alice", **_NO_ROLE})
        assert resp.status_code == 200, resp.text
        assert all(t["slug"] != "foreign" for t in resp.json())
