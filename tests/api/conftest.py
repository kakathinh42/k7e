"""Shared fixtures for API tests: an isolated in-memory SQLite DB + TestClient."""

from __future__ import annotations

import uuid

import k7e_api.db as db_module
import pytest
from fastapi.testclient import TestClient
from k7e_api.main import app
from k7e_api.models import Base, KnowledgeItem, RoleGrant
from k7e_api.tenancy import TenantContext, get_tenant_context
from sqlalchemy import StaticPool, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

# A stable test-only org UUID used to override get_tenant_context in api_client.
# Tests that need real org isolation (e.g. test_tenancy_scoped.py) use sqlite_factory
# directly and create their own orgs — those tests don't rely on this UUID.
_TEST_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
TEST_TENANT_CONTEXT = TenantContext(org_id=_TEST_ORG_ID)


@pytest.fixture(autouse=True)
def _scrub_identity_env(monkeypatch):
    """Scrub identity env vars a developer's real .env leaks into tests.

    ``litellm`` calls ``load_dotenv()`` at import time and ``find_dotenv``
    climbs parent directories — from a ``.claude/worktrees/<name>`` checkout it
    reaches the MAIN checkout's ``.env``, exporting whatever is enabled there
    (JWT_* since the 2026-07-08 SSO enablement; CONFLUENCE_* on dev shells)
    into ``os.environ``, where pydantic Settings picks them up and breaks
    default-value assumptions. Tests that need these values set them
    explicitly via kwargs or monkeypatch.setenv.
    """
    for var in (
        "JWT_ENABLED",
        "JWT_DEV_SECRET",
        "JWT_ISSUER",
        "JWT_AUDIENCE",
        "JWT_JWKS_URL",
        "JWT_TRUSTED_ISSUERS",
        "JWT_IDENTITY_CLAIM",
        "CONFLUENCE_API_TOKEN",
        "CONFLUENCE_USER_EMAIL",
    ):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# Test-only RBAC cutover seeding (Task 4 — M2)
# ---------------------------------------------------------------------------
# Under ``auth_mode="rbac"`` (the new default), ``get_authz`` returns the
# hierarchical RBAC service, which admits a published item only when the caller
# holds a role grant at a scope covering the item's org/space/project AND the
# item carries a non-null containment id. Production reaches that state via
# migrations 0016 (org_id backfill + NOT NULL) and 0017 (the all-org
# ``group:public viewer`` seed). The SQLite test DBs skip migrations
# (``Base.metadata.create_all`` only), so the regression suite — which seeds
# items through the legacy ``upsert_item_version`` / direct-construct paths
# that leave ``org_id`` NULL — would otherwise see an empty allowed set under
# RBAC and fail. This ``before_flush`` hook brings the test DB to the
# post-migration state the RBAC service assumes, mirroring 0016 + 0017 *without
# weakening the service*:
#
#   * default ``org_id`` to the test org on any newly-inserted KnowledgeItem
#     whose ``org_id`` is NULL (the 0016 backfill analog);
#   * seed the ``group:public viewer @ org:<test org>`` grant once per DB (the
#     0017 seed analog) — but only when a KnowledgeItem is being inserted at
#     the test org, so tests that never insert a KnowledgeItem
#     (``test_role_grant_model``) and tests that seed items at a different
#     explicit org (``test_rbac_inheritance``) are left completely untouched.
#
# The grant is added as a pending object in the same flush, so it commits with
# the test's own seed data and is visible to the RBAC read path (the shared
# StaticPool connection keeps it live for the request session). The behavior is
# the behavior-preserving cutover proof: a default caller (``X-User-Groups``
# empty ⇒ implicit ``public`` group) matches the seeded viewer grant and reads
# exactly the public content the legacy group service showed them.
def _seed_test_rbac_on_flush(session, _flush_context, _instances):
    """``before_flush`` hook: default NULL org_id on new items + seed viewer grant."""
    new_kis = [obj for obj in session.new if isinstance(obj, KnowledgeItem)]
    if not new_kis:
        return
    # Only act when at least one new item is at (or being defaulted to) the test
    # org. Items seeded at a different explicit org — e.g. the ``...0a1`` org
    # used by ``test_rbac_inheritance`` — are left alone so the inheritance
    # truth-table and the no-grant fail-closed case stay exact.
    qualifies = False
    for ki in new_kis:
        if ki.org_id is None:
            ki.org_id = _TEST_ORG_ID
            qualifies = True
        elif ki.org_id == _TEST_ORG_ID:
            qualifies = True
    if not qualifies:
        return
    # Seed the viewer grant once per DB. The in-memory test engines use
    # StaticPool (a single shared connection per DB), so a connection-level flag
    # is exactly "once per DB" — and, unlike an existence SELECT, it does not
    # re-enter flush (running a query inside ``before_flush`` recurses and
    # double-inserts the grant). The grant is added as a pending object in this
    # same flush, so it commits with the test's own seed data and is visible to
    # the RBAC read path via the shared connection.
    #
    # Latent limitation: the flag is set before the flush commits, so if a
    # KI-inserting transaction is rolled back the flag persists while the grant
    # insert is undone. No current test rolls back a KI insert and then re-reads
    # expecting the grant (every seeding path commits), so this never bites
    # today; an ``after_rollback`` reset is intentionally avoided because it
    # would re-seed a *duplicate* grant after a later, unrelated rollback when a
    # committed grant already exists (the guard has no DB check by design).
    conn = session.connection()
    if conn.info.get("_m2_rbac_grant_seeded"):
        return
    conn.info["_m2_rbac_grant_seeded"] = True
    session.add(
        RoleGrant(
            principal_kind="group",
            principal_id="public",
            role="viewer",
            scope_kind="org",
            scope_id=_TEST_ORG_ID,
        )
    )


event.listen(Session, "before_flush", _seed_test_rbac_on_flush)


@pytest.fixture()
def sqlite_factory():
    """A sessionmaker bound to a fresh in-memory SQLite DB (one per test)."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False, class_=Session)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def api_client(sqlite_factory):
    """A TestClient with get_session and get_tenant_context overridden to test doubles.

    get_session: uses the per-test in-memory SQLite DB (same as sqlite_factory).
    get_tenant_context: returns a fixed TenantContext so routers that depend on it
        work without a seeded 'default' org in the test DB.  Tests that need real
        multi-tenant isolation should use sqlite_factory directly.
    """

    def _override_get_session():
        session = sqlite_factory()
        try:
            yield session
        finally:
            session.close()

    def _override_get_tenant_context():
        return TEST_TENANT_CONTEXT

    app.dependency_overrides[db_module.get_session] = _override_get_session
    app.dependency_overrides[get_tenant_context] = _override_get_tenant_context
    yield TestClient(app)
    app.dependency_overrides.pop(db_module.get_session, None)
    app.dependency_overrides.pop(get_tenant_context, None)
