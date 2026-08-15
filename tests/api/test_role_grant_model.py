"""Tests for the RoleGrant ORM model (Task 1 — M2 hierarchical RBAC).

A ``RoleGrant`` binds a principal (``user``/``group``/``app``) to a role
(``viewer``/``editor``/``reviewer``/``admin``) at a scope node
(``org``/``space``/``project``). ``scope_id`` is FK-less polymorphic
(discriminated by ``scope_kind``) — referential integrity is enforced in
application code, not the DB. ``role_grants`` is deliberately **not** an
``org_id``-scoped content table (a grant's tenant is implied by its scope), so
these tests never set ``org_id`` and never route through ``scoped()``.
"""

from __future__ import annotations

import uuid

import pytest
from k7e_api.models import Organization, Project, RoleGrant, Space
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# Deterministic UUIDs reused across the matrix so the uniqueness negatives are
# exact-tuple collisions rather than accidental PK clashes.
_ORG_ID = uuid.uuid4()
_SPACE_ID = uuid.uuid4()
_PROJECT_ID = uuid.uuid4()


def _seed_hierarchy(s: Session) -> None:
    """Persist a minimal org → space → project so scope_ids look real (no FKs)."""
    org = Organization(id=_ORG_ID, slug="acme", name="Acme")
    space = Space(id=_SPACE_ID, org_id=_ORG_ID, slug="eng", name="Engineering")
    project = Project(id=_PROJECT_ID, space_id=_SPACE_ID, slug="backend", name="Backend")
    s.add_all([org, space, project])
    s.flush()


def test_role_grant_round_trip_each_kind_role_scope(sqlite_factory):
    """A RoleGrant persists and round-trips for every principal_kind/role/scope_kind."""
    cases = [
        ("user", "alice", "viewer", "org", _ORG_ID),
        ("group", "engineering", "editor", "space", _SPACE_ID),
        ("app", "ci-bot", "reviewer", "project", _PROJECT_ID),
        ("user", "bob", "admin", "org", _ORG_ID),
    ]
    with sqlite_factory() as s:
        _seed_hierarchy(s)
        for kind, pid, role, skind, sid in cases:
            grant = RoleGrant(
                principal_kind=kind,
                principal_id=pid,
                role=role,
                scope_kind=skind,
                scope_id=sid,
            )
            s.add(grant)
            s.flush()
            assert grant.id is not None
            assert grant.created_at is not None

        # Round-trip: read everything back from the DB and assert the columns.
        s.commit()
        s.expire_all()
        grants = s.query(RoleGrant).order_by(RoleGrant.principal_id).all()
        assert len(grants) == 4
        by_key = {
            (g.principal_kind, g.principal_id, g.role, g.scope_kind, str(g.scope_id))
            for g in grants
        }
        for kind, pid, role, skind, sid in cases:
            assert (kind, pid, role, skind, str(sid)) in by_key


def test_role_grant_unique_constraint_rejects_exact_duplicate(sqlite_factory):
    """uq_role_grant rejects a duplicate (principal_kind, principal_id, role, scope_kind, scope_id)."""
    with sqlite_factory() as s:
        _seed_hierarchy(s)
        s.add(
            RoleGrant(
                principal_kind="user",
                principal_id="alice",
                role="viewer",
                scope_kind="org",
                scope_id=_ORG_ID,
            )
        )
        s.flush()

        # Exact same 5-tuple → unique violation.
        s.add(
            RoleGrant(
                principal_kind="user",
                principal_id="alice",
                role="viewer",
                scope_kind="org",
                scope_id=_ORG_ID,
            )
        )
        with pytest.raises(IntegrityError):
            s.flush()


def test_role_grant_unique_allows_same_principal_different_scope(sqlite_factory):
    """Same principal+role at a different scope is allowed (scope is part of the key)."""
    with sqlite_factory() as s:
        _seed_hierarchy(s)
        s.add(
            RoleGrant(
                principal_kind="user",
                principal_id="alice",
                role="viewer",
                scope_kind="org",
                scope_id=_ORG_ID,
            )
        )
        s.flush()

        # Same principal + role, different scope (space instead of org) → OK.
        s.add(
            RoleGrant(
                principal_kind="user",
                principal_id="alice",
                role="viewer",
                scope_kind="space",
                scope_id=_SPACE_ID,
            )
        )
        s.flush()  # should NOT raise
        assert s.query(RoleGrant).count() == 2


def test_role_grant_unique_allows_same_principal_different_role(sqlite_factory):
    """Same principal at the same scope but a different role is allowed."""
    with sqlite_factory() as s:
        _seed_hierarchy(s)
        s.add(
            RoleGrant(
                principal_kind="group",
                principal_id="engineering",
                role="viewer",
                scope_kind="space",
                scope_id=_SPACE_ID,
            )
        )
        s.flush()

        # Same principal + scope, different role (editor) → OK.
        s.add(
            RoleGrant(
                principal_kind="group",
                principal_id="engineering",
                role="editor",
                scope_kind="space",
                scope_id=_SPACE_ID,
            )
        )
        s.flush()  # should NOT raise
        assert s.query(RoleGrant).count() == 2
