"""Implicit ``user:<id>`` self-group for allowed_groups filtering (personal spaces).

Every human principal implicitly carries ``user:<user_id>`` when the
``allowed_groups`` override is evaluated, so an item stamped
``allowed_groups=["user:alice"]`` is visible ONLY to alice — not even an org
admin sees it (the documented personal-spaces deviation: ``allowed_groups`` is
a hard post-grant filter, not overridable by role). The team-group mechanism
is untouched, and grant matching never uses the self-group.

Items are seeded through the conftest ``before_flush`` hook (org_id defaulted
to the test org + the ``group:public viewer @ org`` grant), so every caller
below is grant-admitted and the assertions isolate the allowed_groups filter.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from k7e_api.auth import GroupAuthorizationService, Principal
from k7e_api.models import KnowledgeItem, KnowledgeItemVersion, RoleGrant, Space
from k7e_api.rbac import HierarchicalRbacAuthorizationService, effective_groups
from sqlalchemy import select
from sqlalchemy.orm import Session

_TEST_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _publish(
    session: Session,
    *,
    slug: str,
    allowed_groups: list[str] | None,
    space_id: uuid.UUID | None = None,
    type_: str = "source",
    provenance: dict | None = None,
) -> KnowledgeItem:
    """Seed a published source item; org_id is defaulted by the conftest hook."""
    item = KnowledgeItem(
        slug=slug,
        title=slug,
        status="published",
        type=type_,
        allowed_groups=allowed_groups,
        space_id=space_id,
        provenance=provenance
        if provenance is not None
        else {"resource": None, "source_pages": []},
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(item)
    session.flush()
    version = KnowledgeItemVersion(
        item_id=item.id,
        version_number=1,
        markdown_body=f"# {slug}\n\nbody",
        model_id="t",
        created_by="t",
        citations=[],
        status="published",
        title=slug,
        created_at=_now(),
    )
    session.add(version)
    session.flush()
    item.current_version_id = version.id
    return item


def _seed_items(session: Session) -> None:
    _publish(session, slug="a-personal-alice", allowed_groups=["user:alice"])
    _publish(session, slug="b-public", allowed_groups=None)
    _publish(session, slug="c-team-x", allowed_groups=["team:x"])
    session.commit()


def _slugs(service, principal: Principal, session: Session) -> set[str]:
    ids = service.allowed_item_ids(principal, session)
    if not ids:
        return set()
    rows = session.execute(select(KnowledgeItem.slug).where(KnowledgeItem.id.in_(ids))).all()
    return {row[0] for row in rows}


class TestEffectiveGroupsHelper:
    def test_user_gains_self_group(self):
        p = Principal(user_id="alice", roles=[], groups=["eng"])
        assert effective_groups(p) == {"eng", "public", "user:alice"}

    def test_anonymous_gets_no_self_group(self):
        p = Principal(user_id="anonymous", roles=[], groups=[])
        assert effective_groups(p) == {"public"}

    def test_empty_user_id_gets_no_self_group(self):
        p = Principal(user_id="", roles=[], groups=[])
        assert effective_groups(p) == {"public"}

    def test_app_principal_gets_no_self_group(self):
        p = Principal(user_id="myapp", kind="app", roles=[], groups=[])
        assert effective_groups(p) == {"public"}


class TestPersonalVisibilityRbac:
    """HierarchicalRbacAuthorizationService.allowed_item_ids under the
    conftest-seeded public viewer grant."""

    def test_owner_sees_personal_and_public(self, sqlite_factory):
        with sqlite_factory() as s:
            _seed_items(s)
            service = HierarchicalRbacAuthorizationService()
            alice = Principal(user_id="alice", roles=[], groups=[])
            assert _slugs(service, alice, s) == {"a-personal-alice", "b-public"}

    def test_other_user_sees_only_public(self, sqlite_factory):
        with sqlite_factory() as s:
            _seed_items(s)
            service = HierarchicalRbacAuthorizationService()
            bob = Principal(user_id="bob", roles=[], groups=[])
            assert _slugs(service, bob, s) == {"b-public"}

    def test_org_admin_cannot_read_personal_items(self, sqlite_factory):
        """The documented deviation: allowed_groups is a hard filter — an org
        admin grant does not pierce another user's personal items."""
        with sqlite_factory() as s:
            _seed_items(s)
            s.add(
                RoleGrant(
                    principal_kind="user",
                    principal_id="carol",
                    role="admin",
                    scope_kind="org",
                    scope_id=_TEST_ORG_ID,
                )
            )
            s.commit()
            service = HierarchicalRbacAuthorizationService()
            carol = Principal(user_id="carol", roles=[], groups=[])
            assert _slugs(service, carol, s) == {"b-public"}

    def test_team_group_mechanism_untouched(self, sqlite_factory):
        """Regression: a declared team group still admits its items."""
        with sqlite_factory() as s:
            _seed_items(s)
            service = HierarchicalRbacAuthorizationService()
            dave = Principal(user_id="dave", roles=[], groups=["team:x"])
            assert _slugs(service, dave, s) == {"b-public", "c-team-x"}


class TestPersonalVisibilityGroupService:
    """The legacy GroupAuthorizationService intersection site gets the same
    self-group (auth_mode='groups' deployments stay consistent)."""

    def test_owner_sees_personal_others_do_not(self, sqlite_factory):
        with sqlite_factory() as s:
            _seed_items(s)
            service = GroupAuthorizationService()
            alice = Principal(user_id="alice", roles=[], groups=[])
            bob = Principal(user_id="bob", roles=[], groups=[])
            assert _slugs(service, alice, s) == {"a-personal-alice", "b-public"}
            assert _slugs(service, bob, s) == {"b-public"}


class TestOwnedSpaceNullAclBackstop:
    """Regression for the cross-user leak: a personal-space item whose
    allowed_groups is NULL (the exact shape ingest paths like conversation
    mirroring were producing) must still be owner-only. This is the
    defense-in-depth backstop in rbac — independent of whether the mirror
    stamps the ACL correctly."""

    def _make_personal_space(self, session: Session, *, owner: str) -> uuid.UUID:
        space = Space(
            org_id=_TEST_ORG_ID,
            slug=f"personal-{owner}",
            name=f"{owner}'s space",
            owner_user_id=owner,
        )
        session.add(space)
        session.flush()
        return space.id

    def test_owner_sees_null_acl_personal_source(self, sqlite_factory):
        with sqlite_factory() as s:
            space_id = self._make_personal_space(s, owner="alice")
            _publish(
                s,
                slug="leak-source-alice",
                allowed_groups=None,
                space_id=space_id,
            )
            s.commit()
            service = HierarchicalRbacAuthorizationService()
            alice = Principal(user_id="alice", roles=[], groups=[])
            assert _slugs(service, alice, s) == {"leak-source-alice"}

    def test_non_owner_cannot_see_null_acl_personal_source(self, sqlite_factory):
        with sqlite_factory() as s:
            space_id = self._make_personal_space(s, owner="alice")
            _publish(
                s,
                slug="leak-source-alice",
                allowed_groups=None,
                space_id=space_id,
            )
            s.commit()
            service = HierarchicalRbacAuthorizationService()
            bob = Principal(user_id="bob", roles=[], groups=[])
            assert _slugs(service, bob, s) == set()

    def test_org_admin_cannot_see_null_acl_personal_source(self, sqlite_factory):
        """The documented deviation extends to the null-ACL backstop: an org
        admin grant does not pierce another user's owned space either."""
        with sqlite_factory() as s:
            space_id = self._make_personal_space(s, owner="alice")
            _publish(
                s,
                slug="leak-source-alice",
                allowed_groups=None,
                space_id=space_id,
            )
            s.add(
                RoleGrant(
                    principal_kind="user",
                    principal_id="carol",
                    role="admin",
                    scope_kind="org",
                    scope_id=_TEST_ORG_ID,
                )
            )
            s.commit()
            service = HierarchicalRbacAuthorizationService()
            carol = Principal(user_id="carol", roles=[], groups=[])
            assert _slugs(service, carol, s) == set()

    def test_owner_sees_null_acl_personal_derived_page(self, sqlite_factory):
        """A derived page (type != 'source') in the owned space, provenance
        pointing at the null-ACL source, is owner-visible."""
        with sqlite_factory() as s:
            space_id = self._make_personal_space(s, owner="alice")
            _publish(
                s,
                slug="leak-source-alice",
                allowed_groups=None,
                space_id=space_id,
            )
            _publish(
                s,
                slug="leak-derived-alice",
                allowed_groups=None,
                space_id=space_id,
                type_="entity",
                provenance={"resource": None, "source_pages": ["leak-source-alice"]},
            )
            s.commit()
            service = HierarchicalRbacAuthorizationService()
            alice = Principal(user_id="alice", roles=[], groups=[])
            assert _slugs(service, alice, s) == {
                "leak-source-alice",
                "leak-derived-alice",
            }

    def test_non_owner_cannot_see_null_acl_personal_derived_page(self, sqlite_factory):
        with sqlite_factory() as s:
            space_id = self._make_personal_space(s, owner="alice")
            _publish(
                s,
                slug="leak-source-alice",
                allowed_groups=None,
                space_id=space_id,
            )
            _publish(
                s,
                slug="leak-derived-alice",
                allowed_groups=None,
                space_id=space_id,
                type_="entity",
                provenance={"resource": None, "source_pages": ["leak-source-alice"]},
            )
            s.commit()
            service = HierarchicalRbacAuthorizationService()
            bob = Principal(user_id="bob", roles=[], groups=[])
            assert _slugs(service, bob, s) == set()
