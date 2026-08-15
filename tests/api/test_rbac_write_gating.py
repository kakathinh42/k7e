"""Write-path RBAC gating (Task 5 — M2).

End-to-end enforcement proof at the HTTP layer for the routes that mutate state:

* ``POST /ingest/upload``  — requires ``editor`` at ``Scope("org", ctx.org_id)``.
* ``DELETE /items/{slug}`` — requires ``editor`` at the item's narrowest
  containment scope, **after** the read-visibility check (so an unauthorized
  reader gets 404, not a role-leaking 403).

The matrix (from the spec Testing Strategy) exercises both authority paths:

* **Header back-compat** — ``X-User-Roles: editor``/``reviewer``/``admin``
  short-circuit ``can_write`` (the default ``reviewer`` header keeps the
  existing suite green); ``viewer`` does not.
* **Grants** — a ``RoleGrant`` (editor) at a covering scope authorizes
  a caller with no privileged header role, and scope specificity holds: a
  space-A grant does not cover a space-B (or org-scoped) action; an org grant
  covers both.

Grant-based cases go through ``gated_client``, which overrides ``get_authz`` to
the hierarchical RBAC service bound to the test's in-memory DB (the default
``get_authz()`` service opens ``SessionLocal`` — the production engine — for its
grant walk, so it could never see test-seeded grants). Header back-compat is
unaffected: the service checks ``X-User-Roles`` before walking grants.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from k7e_api.auth import get_authz
from k7e_api.deps import get_object_store, get_workflow_starter
from k7e_api.main import app
from k7e_api.models import (
    KnowledgeItem,
    KnowledgeItemVersion,
    Organization,
    Project,
    RoleGrant,
    Space,
)
from k7e_api.object_store import LocalFileObjectStore
from k7e_api.rbac import HierarchicalRbacAuthorizationService

from tests.api.conftest import TEST_TENANT_CONTEXT

# The test org is the same one TEST_TENANT_CONTEXT resolves to (so the
# ingest org-scoped gate and the auto-seeded ``group:public viewer`` grant line
# up with the items' org_id).
_ORG_ID = TEST_TENANT_CONTEXT.org_id
_SPACE_ENG_ID = uuid.UUID("00000000-0000-0000-0000-0000000000d1")
_SPACE_FIN_ID = uuid.UUID("00000000-0000-0000-0000-0000000000d2")
_PROJ_ENG_CORE_ID = uuid.UUID("00000000-0000-0000-0000-0000000000d3")

# A small valid markdown upload reused across the ingest matrix.
_UPLOAD = {"file": ("doc.md", b"# Title\nhello", "text/markdown")}

# ``reader`` is a non-privileged sentinel header role: it is not in
# {editor, reviewer, admin, viewer}, so it never short-circuits can_write —
# the grant walk is the sole authority.
_NO_ROLE = {"X-User-Roles": "reader"}


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _publish(
    session,
    *,
    slug: str,
    title: str,
    org_id: uuid.UUID,
    space_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    allowed_groups: list[str] | None = None,
) -> KnowledgeItem:
    """Seed one published source item + version at a containment level."""
    item = KnowledgeItem(
        org_id=org_id,
        space_id=space_id,
        project_id=project_id,
        slug=slug,
        title=title,
        status="published",
        type="source",
        allowed_groups=allowed_groups,
        provenance={"resource": None, "source_pages": []},
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


def _grant(
    session,
    *,
    principal_id: str,
    role: str,
    scope_kind: str,
    scope_id: uuid.UUID,
    principal_kind: str = "user",
) -> None:
    """Seed + commit a RoleGrant."""
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


def _seed_hierarchy(session) -> None:
    """One org, two sibling spaces, one project in the eng space (no items)."""
    session.add(Organization(id=_ORG_ID, slug="test-org", name="Test Org"))
    session.add_all(
        [
            Space(id=_SPACE_ENG_ID, org_id=_ORG_ID, slug="eng", name="Engineering"),
            Space(id=_SPACE_FIN_ID, org_id=_ORG_ID, slug="fin", name="Finance"),
        ]
    )
    session.add(Project(id=_PROJ_ENG_CORE_ID, space_id=_SPACE_ENG_ID, slug="core", name="Core"))
    session.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def gated_client(api_client, sqlite_factory):
    """``api_client`` + ``get_authz`` → RBAC service bound to the test DB.

    The default ``get_authz()`` returns ``HierarchicalRbacAuthorizationService()``
    with no ``session_factory``, so its grant walks open ``SessionLocal`` (the
    production engine) and never see test-seeded grants. Binding the service to
    the test's ``sqlite_factory`` makes grant-based ``can_write``/``can_review``
    cases exercisable through the HTTP layer. Header back-compat is unaffected
    (the service checks ``X-User-Roles`` before walking grants).
    """
    app.dependency_overrides[get_authz] = lambda: HierarchicalRbacAuthorizationService(
        session_factory=sqlite_factory
    )
    yield api_client
    app.dependency_overrides.pop(get_authz, None)


@pytest.fixture()
def ingest_client(gated_client, tmp_path):
    """``gated_client`` + object_store (tmp) + workflow_starter (fake) overrides.

    ``POST /ingest/upload`` otherwise calls the real Temporal starter; the
    editor-accepted cases need the write gate to pass AND the handler to finish,
    so both external deps are stubbed (mirrors tests/api/test_ingest_upload.py).
    """
    app.dependency_overrides[get_object_store] = lambda: LocalFileObjectStore(str(tmp_path))

    def _fake_starter(raw_document_id: str) -> str:
        return "wf-test"

    app.dependency_overrides[get_workflow_starter] = lambda: _fake_starter
    yield gated_client
    app.dependency_overrides.pop(get_object_store, None)
    app.dependency_overrides.pop(get_workflow_starter, None)


@pytest.fixture()
def seeded_archive_db(sqlite_factory):
    """Seed the hierarchy + two ``allowed_groups=["secret"]`` source items.

    Inserting the items at ``_ORG_ID`` triggers conftest's ``before_flush``
    hook, which auto-seeds the ``group:public viewer @ org`` grant — so a
    ``secret``-group caller can READ the items (org viewer admits, then the
    ``secret`` allowed_group passes) while a public-only caller cannot (404).
    Grants are NOT seeded here — each test adds exactly the grant it exercises.
    """
    with sqlite_factory() as s:
        _seed_hierarchy(s)
        _publish(
            s,
            slug="arch-space-src",
            title="Arch Space Src",
            org_id=_ORG_ID,
            space_id=_SPACE_ENG_ID,
            allowed_groups=["secret"],
        )
        _publish(
            s,
            slug="arch-proj-src",
            title="Arch Proj Src",
            org_id=_ORG_ID,
            space_id=_SPACE_ENG_ID,
            project_id=_PROJ_ENG_CORE_ID,
            allowed_groups=["secret"],
        )
        s.commit()


# ===========================================================================
# Ingest — POST /ingest/upload requires editor at Scope("org", ctx.org_id)
# ===========================================================================


class TestIngestGating:
    def test_editor_header_accepted(self, ingest_client):
        resp = ingest_client.post(
            "/ingest/upload", files=_UPLOAD, headers={"X-User-Roles": "editor"}
        )
        assert resp.status_code == 200, resp.text

    def test_reviewer_header_accepted_implies_editor(self, ingest_client):
        resp = ingest_client.post(
            "/ingest/upload",
            files=_UPLOAD,
            headers={"X-User-Id": "alice", "X-User-Roles": "reviewer"},
        )
        assert resp.status_code == 200, resp.text

    def test_admin_header_accepted_implies_editor(self, ingest_client):
        resp = ingest_client.post(
            "/ingest/upload",
            files=_UPLOAD,
            headers={"X-User-Id": "alice", "X-User-Roles": "admin"},
        )
        assert resp.status_code == 200, resp.text

    def test_viewer_only_denied_403(self, ingest_client):
        resp = ingest_client.post(
            "/ingest/upload",
            files=_UPLOAD,
            headers={"X-User-Id": "alice", "X-User-Roles": "viewer"},
        )
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"] == "Editor role required"

    def test_editor_grant_at_org_accepted(self, ingest_client, sqlite_factory):
        with sqlite_factory() as s:
            _grant(
                s,
                principal_id="alice",
                role="editor",
                scope_kind="org",
                scope_id=_ORG_ID,
            )
        resp = ingest_client.post(
            "/ingest/upload",
            files=_UPLOAD,
            headers={"X-User-Id": "alice", **_NO_ROLE},
        )
        assert resp.status_code == 200, resp.text

    def test_viewer_grant_at_org_denied_403(self, ingest_client, sqlite_factory):
        """A viewer grant confers read, not write — the write gate still denies."""
        with sqlite_factory() as s:
            _grant(
                s,
                principal_id="alice",
                role="viewer",
                scope_kind="org",
                scope_id=_ORG_ID,
            )
        resp = ingest_client.post(
            "/ingest/upload",
            files=_UPLOAD,
            headers={"X-User-Id": "alice", **_NO_ROLE},
        )
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"] == "Editor role required"


# ===========================================================================
# Archive — DELETE /items/{slug} requires editor at the item's narrowest scope,
# AFTER the read-visibility check (404 for non-readers, 403 for readers).
# ===========================================================================


_SECRET_EDITOR = {
    "X-User-Id": "alice",
    "X-User-Roles": "editor",
    "X-User-Groups": "secret",
}
_SECRET_VIEWER = {
    "X-User-Id": "alice",
    "X-User-Roles": "viewer",
    "X-User-Groups": "secret",
}
_PUBLIC_NON_READER = {"X-User-Id": "nobody", "X-User-Roles": "reader"}


class TestArchiveGating:
    def test_editor_header_archives_space_item(self, gated_client, seeded_archive_db):
        resp = gated_client.delete("/items/arch-space-src", headers=_SECRET_EDITOR)
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "archived"

    def test_viewer_who_can_read_is_403(self, gated_client, seeded_archive_db):
        # The viewer can READ the item (secret group) but cannot write — so the
        # write gate fires (403), not the read check (404).
        resp = gated_client.delete("/items/arch-space-src", headers=_SECRET_VIEWER)
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"] == "Editor role required"

    def test_non_reader_is_404_not_403(self, gated_client, seeded_archive_db):
        # A public-only caller cannot read the secret item — the read-visibility
        # check fires FIRST (404), never reaching the write gate (no 403 leak).
        resp = gated_client.delete("/items/arch-space-src", headers=_PUBLIC_NON_READER)
        assert resp.status_code == 404, resp.text
        assert resp.json()["detail"] == "Item not found"

    def test_editor_grant_on_item_space_archives(
        self, gated_client, seeded_archive_db, sqlite_factory
    ):
        with sqlite_factory() as s:
            _grant(
                s,
                principal_id="alice",
                role="editor",
                scope_kind="space",
                scope_id=_SPACE_ENG_ID,
            )
        resp = gated_client.delete(
            "/items/arch-space-src",
            headers={"X-User-Id": "alice", "X-User-Groups": "secret", **_NO_ROLE},
        )
        assert resp.status_code == 200, resp.text

    def test_editor_grant_on_sibling_space_denied(
        self, gated_client, seeded_archive_db, sqlite_factory
    ):
        """Scope specificity: an editor grant on the fin space does not cover the eng-space item."""
        with sqlite_factory() as s:
            _grant(
                s,
                principal_id="alice",
                role="editor",
                scope_kind="space",
                scope_id=_SPACE_FIN_ID,
            )
        resp = gated_client.delete(
            "/items/arch-space-src",
            headers={"X-User-Id": "alice", "X-User-Groups": "secret", **_NO_ROLE},
        )
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"] == "Editor role required"

    def test_editor_grant_on_project_archives_project_item(
        self, gated_client, seeded_archive_db, sqlite_factory
    ):
        with sqlite_factory() as s:
            _grant(
                s,
                principal_id="alice",
                role="editor",
                scope_kind="project",
                scope_id=_PROJ_ENG_CORE_ID,
            )
        resp = gated_client.delete(
            "/items/arch-proj-src",
            headers={"X-User-Id": "alice", "X-User-Groups": "secret", **_NO_ROLE},
        )
        assert resp.status_code == 200, resp.text

    def test_editor_grant_on_sibling_space_denied_for_project_item(
        self, gated_client, seeded_archive_db, sqlite_factory
    ):
        """A fin-space editor grant does not cover a project in the eng space."""
        with sqlite_factory() as s:
            _grant(
                s,
                principal_id="alice",
                role="editor",
                scope_kind="space",
                scope_id=_SPACE_FIN_ID,
            )
        resp = gated_client.delete(
            "/items/arch-proj-src",
            headers={"X-User-Id": "alice", "X-User-Groups": "secret", **_NO_ROLE},
        )
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"] == "Editor role required"
