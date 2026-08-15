"""Tests for the ``space`` field on POST /ingest/upload (Task 7).

Covers the personal-spaces plan's Task 7 acceptance gate:

1. no ``space`` -> legacy org-gated path, byte-identical (``space_id`` NULL),
   plus the new ``created_by`` provenance stamp.
2. ``space=personal`` JIT-provisions the caller's own Space, force-stamps
   ``allowed_groups=["user:<id>"]`` (personal is not shareable in v1), and
   stamps ``space_id``/``created_by``.
3. a second ``space=personal`` upload by the same user reuses the same Space
   (idempotent JIT).
4. an unknown non-personal slug 404s (ingest never auto-creates a team space).
5. a team/org space enforces the real write gate: a non-member without an org
   grant gets 403; an org-editor gets 200.
6. the personal daily ingest cap 429s past the limit; a team-space upload
   does not count against it.

Fixtures mirror ``tests/api/test_ingest_upload.py`` (sqlite session factory +
LocalFileObjectStore + fake workflow starter + dependency overrides), plus a
``get_authz`` override binding the RBAC service to the same in-memory DB
(mirrors ``tests/api/test_rbac_write_gating.py::ingest_client``) so grant-based
write-gate checks (not just the dev/header back-compat) are exercisable.
"""

from __future__ import annotations

import uuid

import k7e_api.db as db_module
import pytest
from fastapi.testclient import TestClient
from k7e_api.auth import get_authz
from k7e_api.config import get_settings
from k7e_api.deps import get_object_store, get_workflow_starter
from k7e_api.main import app
from k7e_api.models import Base, RawDocument, RoleGrant, Space
from k7e_api.object_store import LocalFileObjectStore
from k7e_api.rbac import HierarchicalRbacAuthorizationService
from k7e_api.tenancy import get_tenant_context
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

from tests.api.conftest import TEST_TENANT_CONTEXT

# ---------------------------------------------------------------------------
# Fixtures (mirrors tests/api/test_ingest_upload.py, + a session-bound authz
# override so grant-based write-gate checks see test-seeded RoleGrants).
# ---------------------------------------------------------------------------


@pytest.fixture()
def sqlite_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def sqlite_session_factory(sqlite_engine):
    return sessionmaker(sqlite_engine, expire_on_commit=False, class_=Session)


@pytest.fixture()
def started_workflow_ids():
    return []


@pytest.fixture()
def client(tmp_path, sqlite_session_factory, started_workflow_ids):
    def override_get_session():
        session = sqlite_session_factory()
        try:
            yield session
        finally:
            session.close()

    def override_get_object_store():
        return LocalFileObjectStore(str(tmp_path))

    def override_get_workflow_starter():
        def fake_starter(raw_document_id: str) -> str:
            started_workflow_ids.append(raw_document_id)
            return "wf-test-123"

        return fake_starter

    app.dependency_overrides[db_module.get_session] = override_get_session
    app.dependency_overrides[get_object_store] = override_get_object_store
    app.dependency_overrides[get_workflow_starter] = override_get_workflow_starter
    app.dependency_overrides[get_tenant_context] = lambda: TEST_TENANT_CONTEXT
    # The default get_authz() opens SessionLocal() (the production engine) for
    # its grant walk, so it can never see test-seeded RoleGrants. Bind it to
    # this test's in-memory DB (mirrors test_rbac_write_gating.py::ingest_client).
    app.dependency_overrides[get_authz] = lambda: HierarchicalRbacAuthorizationService(
        session_factory=sqlite_session_factory
    )

    yield TestClient(app)

    app.dependency_overrides.clear()


def _seed_team_space(sqlite_session_factory, *, slug: str = "eng") -> uuid.UUID:
    with sqlite_session_factory() as s:
        space = Space(org_id=TEST_TENANT_CONTEXT.org_id, slug=slug, name=slug)
        s.add(space)
        s.commit()
        return space.id


def _grant(sqlite_session_factory, *, principal_id: str, role: str, scope_id) -> None:
    with sqlite_session_factory() as s:
        s.add(
            RoleGrant(
                principal_kind="user",
                principal_id=principal_id,
                role=role,
                scope_kind="org",
                scope_id=scope_id,
            )
        )
        s.commit()


_MD_FILE = {"file": ("doc.md", b"# Title\nhello", "text/markdown")}

# A non-privileged sentinel role: never short-circuits can_write, forcing the
# real grant walk (mirrors test_rbac_write_gating.py's _NO_ROLE).
_NO_ROLE = {"X-User-Roles": "reader"}


# ---------------------------------------------------------------------------
# 1. No `space` field -> legacy org-gated path, byte-identical.
# ---------------------------------------------------------------------------


def test_upload_without_space_is_legacy_regression(client, sqlite_session_factory):
    resp = client.post("/ingest/upload", files=_MD_FILE)
    assert resp.status_code == 200, resp.text
    rid = resp.json()["raw_document_id"]
    with sqlite_session_factory() as s:
        rd = s.get(RawDocument, uuid.UUID(str(rid)))
        assert rd.space_id is None
        # New provenance stamp — the one permitted deviation from byte-identical.
        assert rd.created_by == "dev"  # dev env, no X-User-Id header


# ---------------------------------------------------------------------------
# 2. space=personal JIT-provisions + force-stamps allowed_groups/space_id.
# ---------------------------------------------------------------------------


class _DenyingSpaceAuthz:
    """Authorization double whose ``can_write`` denies EVERY space scope.

    Simulates the prod race the owner-by-construction fix guards against: the
    personal space's editor/admin grants were just flushed (not committed), so
    the RBAC grant walk — which opens a separate DB connection — cannot see
    them yet and returns False. If the owner path consulted this lookup it would
    403; asserting a 200 proves it does not. ``can_write`` at org scope still
    passes so the no-space legacy path is unaffected by the override.
    """

    def can_write(self, principal, scope=None) -> bool:
        return not (scope is not None and scope.kind == "space")

    def can_review(self, principal, scope=None) -> bool:
        return True

    def can_admin(self, principal, scope=None) -> bool:
        return True

    def allowed_item_ids(self, principal, session):
        return None


def test_upload_space_personal_owner_authorized_by_construction(client, sqlite_session_factory):
    """Owner path must NOT depend on the (cross-session, possibly-invisible)
    grant lookup: even when ``can_write`` denies every space scope, a verified
    owner's personal upload succeeds and is stamped correctly."""
    app.dependency_overrides[get_authz] = lambda: _DenyingSpaceAuthz()
    try:
        resp = client.post(
            "/ingest/upload",
            files=_MD_FILE,
            data={"space": "personal"},
            headers={"X-User-Id": "alice"},
        )
    finally:
        # Restore the DB-bound RBAC override the ``client`` fixture installed.
        app.dependency_overrides[get_authz] = lambda: HierarchicalRbacAuthorizationService(
            session_factory=sqlite_session_factory
        )
    assert resp.status_code == 200, resp.text
    rid = resp.json()["raw_document_id"]
    with sqlite_session_factory() as s:
        rd = s.get(RawDocument, uuid.UUID(str(rid)))
        assert rd.space_id is not None
        assert rd.allowed_groups == ["user:alice"]
        assert rd.created_by == "alice"


def test_upload_space_personal_provisions_and_stamps(client, sqlite_session_factory):
    resp = client.post(
        "/ingest/upload",
        files=_MD_FILE,
        data={"space": "personal"},
        headers={"X-User-Id": "alice"},
    )
    assert resp.status_code == 200, resp.text
    rid = resp.json()["raw_document_id"]
    with sqlite_session_factory() as s:
        rd = s.get(RawDocument, uuid.UUID(str(rid)))
        assert rd.space_id is not None
        assert rd.created_by == "alice"
        assert rd.allowed_groups == ["user:alice"]
        space = s.get(Space, rd.space_id)
        assert space is not None
        assert space.owner_user_id == "alice"


def test_upload_space_personal_overrides_form_allowed_groups(client, sqlite_session_factory):
    """Personal is not shareable in v1: a form-supplied CSV is overridden."""
    resp = client.post(
        "/ingest/upload",
        files=_MD_FILE,
        data={"space": "personal", "allowed_groups": "finance, eng"},
        headers={"X-User-Id": "alice"},
    )
    assert resp.status_code == 200, resp.text
    rid = resp.json()["raw_document_id"]
    with sqlite_session_factory() as s:
        rd = s.get(RawDocument, uuid.UUID(str(rid)))
        assert rd.allowed_groups == ["user:alice"]


# ---------------------------------------------------------------------------
# 3. Idempotent JIT: a second personal upload reuses the same Space.
# ---------------------------------------------------------------------------


def test_upload_space_personal_idempotent_jit(client, sqlite_session_factory):
    resp1 = client.post(
        "/ingest/upload",
        files={"file": ("doc1.md", b"# One", "text/markdown")},
        data={"space": "personal"},
        headers={"X-User-Id": "alice"},
    )
    resp2 = client.post(
        "/ingest/upload",
        files={"file": ("doc2.md", b"# Two", "text/markdown")},
        data={"space": "personal"},
        headers={"X-User-Id": "alice"},
    )
    assert resp1.status_code == 200, resp1.text
    assert resp2.status_code == 200, resp2.text
    with sqlite_session_factory() as s:
        rd1 = s.get(RawDocument, uuid.UUID(str(resp1.json()["raw_document_id"])))
        rd2 = s.get(RawDocument, uuid.UUID(str(resp2.json()["raw_document_id"])))
        assert rd1.space_id == rd2.space_id
        assert s.query(Space).filter(Space.owner_user_id == "alice").count() == 1


# ---------------------------------------------------------------------------
# 4. Unknown non-personal slug -> 404 (never auto-created).
# ---------------------------------------------------------------------------


def test_upload_space_unknown_slug_404(client):
    resp = client.post(
        "/ingest/upload",
        files=_MD_FILE,
        data={"space": "no-such-space"},
    )
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# 5. Team/org space: real write-gate enforcement.
# ---------------------------------------------------------------------------


def test_upload_space_team_forbidden_without_grant(client, sqlite_session_factory):
    _seed_team_space(sqlite_session_factory)
    resp = client.post(
        "/ingest/upload",
        files=_MD_FILE,
        data={"space": "eng"},
        headers={"X-User-Id": "bob", **_NO_ROLE},
    )
    assert resp.status_code == 403, resp.text


def test_upload_space_team_allowed_for_org_editor(client, sqlite_session_factory):
    _seed_team_space(sqlite_session_factory)
    _grant(
        sqlite_session_factory,
        principal_id="alice",
        role="editor",
        scope_id=TEST_TENANT_CONTEXT.org_id,
    )
    resp = client.post(
        "/ingest/upload",
        files=_MD_FILE,
        data={"space": "eng"},
        headers={"X-User-Id": "alice", **_NO_ROLE},
    )
    assert resp.status_code == 200, resp.text
    rid = resp.json()["raw_document_id"]
    with sqlite_session_factory() as s:
        rd = s.get(RawDocument, uuid.UUID(str(rid)))
        assert rd.created_by == "alice"
        # Team/org spaces are NOT force-restricted to a self-group.
        assert rd.allowed_groups is None


# ---------------------------------------------------------------------------
# 6. Personal daily ingest cap.
# ---------------------------------------------------------------------------


def test_personal_cap_enforced_team_space_not_counted(client, sqlite_session_factory, monkeypatch):
    monkeypatch.setenv("PERSONAL_INGEST_DAILY_CAP", "2")
    get_settings.cache_clear()
    try:
        _seed_team_space(sqlite_session_factory, slug="eng")
        headers = {"X-User-Id": "alice"}  # dev env default role -> reviewer

        r1 = client.post(
            "/ingest/upload",
            files={"file": ("a.md", b"# A", "text/markdown")},
            data={"space": "personal"},
            headers=headers,
        )
        r2 = client.post(
            "/ingest/upload",
            files={"file": ("b.md", b"# B", "text/markdown")},
            data={"space": "personal"},
            headers=headers,
        )
        assert r1.status_code == 200, r1.text
        assert r2.status_code == 200, r2.text

        r3 = client.post(
            "/ingest/upload",
            files={"file": ("c.md", b"# C", "text/markdown")},
            data={"space": "personal"},
            headers=headers,
        )
        assert r3.status_code == 429, r3.text

        # A team-space upload is NOT gated by the personal cap.
        r4 = client.post(
            "/ingest/upload",
            files={"file": ("d.md", b"# D", "text/markdown")},
            data={"space": "eng"},
            headers=headers,
        )
        assert r4.status_code == 200, r4.text
    finally:
        get_settings.cache_clear()
