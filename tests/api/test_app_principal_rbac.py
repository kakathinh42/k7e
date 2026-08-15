"""M6: an app principal is gated by app RoleGrants (not user/group), no backdoor."""

from __future__ import annotations

import uuid

from k7e_api.auth import Principal, Scope, _dev_backdoor
from k7e_api.models import RoleGrant
from k7e_api.rbac import HierarchicalRbacAuthorizationService


def _app(slug="myapp"):
    return Principal(kind="app", user_id=slug, roles=[], groups=[])


def test_app_with_editor_grant_can_write(sqlite_factory):
    org = uuid.uuid4()
    with sqlite_factory() as s:
        s.add(
            RoleGrant(
                principal_kind="app",
                principal_id="myapp",
                role="editor",
                scope_kind="org",
                scope_id=org,
            )
        )
        s.commit()
    authz = HierarchicalRbacAuthorizationService(session_factory=sqlite_factory)
    assert authz.can_write(_app(), Scope("org", org)) is True


def test_app_without_grant_cannot_write(sqlite_factory):
    org = uuid.uuid4()
    authz = HierarchicalRbacAuthorizationService(session_factory=sqlite_factory)
    assert authz.can_write(_app(), Scope("org", org)) is False


def test_app_does_not_match_user_or_group_grants(sqlite_factory):
    org = uuid.uuid4()
    with sqlite_factory() as s:
        # a USER grant with the same principal_id must NOT admit the app
        s.add(
            RoleGrant(
                principal_kind="user",
                principal_id="myapp",
                role="editor",
                scope_kind="org",
                scope_id=org,
            )
        )
        s.commit()
    authz = HierarchicalRbacAuthorizationService(session_factory=sqlite_factory)
    assert authz.can_write(_app(), Scope("org", org)) is False


def test_app_named_dev_gets_no_backdoor():
    assert _dev_backdoor(Principal(kind="app", user_id="dev", roles=[], groups=[])) is False
