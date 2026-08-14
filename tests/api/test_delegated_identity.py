"""get_effective_principal: a delegation-allowed app may act on behalf of a user."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from k7e_api.app_auth import generate_app_key, get_effective_principal
from k7e_api.auth import Principal
from k7e_api.models import ClientApp, Organization
from k7e_api.tenancy import TenantContext
from sqlalchemy import select


def _seed_app(session, *, delegate: bool, domain: str | None = None):
    org = Organization(slug="o", name="O")
    session.add(org)
    session.flush()
    plaintext, key_hash = generate_app_key()
    app = ClientApp(
        org_id=org.id,
        slug="chat-agent",
        name="CA",
        api_key_hash=key_hash,
        can_delegate_identity=delegate,
        allowed_identity_domain=domain,
    )
    session.add(app)
    session.commit()
    return plaintext


_BASE = Principal(user_id="anonymous", kind="user", roles=[])  # get_principal fallback


def test_delegation_allowed_app_yields_verified_user(sqlite_factory):
    with sqlite_factory() as session:
        key = _seed_app(session, delegate=True)
        app = session.execute(select(ClientApp)).scalars().one()
        p = get_effective_principal(
            x_app_key=key,
            x_on_behalf_of_email="Alice@example.com",
            session=session,
            principal=_BASE,
            ctx=TenantContext(org_id=app.org_id),  # matching org: org guard admits
        )
        assert p.kind == "user"
        assert p.user_id == "alice@example.com"  # normalized lower-case
        assert p.verified is True


def test_non_delegation_app_ignores_header(sqlite_factory):
    with sqlite_factory() as session:
        key = _seed_app(session, delegate=False)
        p = get_effective_principal(
            x_app_key=key,
            x_on_behalf_of_email="alice@example.com",
            session=session,
            principal=_BASE,
        )
        assert p is _BASE  # header ignored — no impersonation


def test_no_app_key_ignores_header(sqlite_factory):
    with sqlite_factory() as session:
        _seed_app(session, delegate=True)
        p = get_effective_principal(
            x_app_key=None,
            x_on_behalf_of_email="alice@example.com",
            session=session,
            principal=_BASE,
        )
        assert p is _BASE


def test_bad_email_400(sqlite_factory):
    with sqlite_factory() as session:
        key = _seed_app(session, delegate=True)
        with pytest.raises(HTTPException) as exc:
            get_effective_principal(
                x_app_key=key,
                x_on_behalf_of_email="not-an-email",
                session=session,
                principal=_BASE,
            )
        assert exc.value.status_code == 400


def test_domain_guard_403(sqlite_factory):
    with sqlite_factory() as session:
        key = _seed_app(session, delegate=True, domain="example.com")
        with pytest.raises(HTTPException) as exc:
            get_effective_principal(
                x_app_key=key,
                x_on_behalf_of_email="mallory@evil.com",
                session=session,
                principal=_BASE,
            )
        assert exc.value.status_code == 403


def test_double_at_email_400(sqlite_factory):
    with sqlite_factory() as session:
        key = _seed_app(session, delegate=True)
        with pytest.raises(HTTPException) as exc:
            get_effective_principal(
                x_app_key=key,
                x_on_behalf_of_email="a@b@example.com",
                session=session,
                principal=_BASE,
            )
        assert exc.value.status_code == 400


def test_empty_local_part_400(sqlite_factory):
    with sqlite_factory() as session:
        key = _seed_app(session, delegate=True)
        with pytest.raises(HTTPException) as exc:
            get_effective_principal(
                x_app_key=key,
                x_on_behalf_of_email="@example.com",
                session=session,
                principal=_BASE,
            )
        assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# F4 (security-review addendum): a delegation-allowed app may only assert an
# identity within its OWN org — get_tenant_context resolves org from
# settings.default_org_slug (not caller-controllable) today, but this guard
# makes the resolver safe even if that changes, or if an app row's org_id
# ever diverges from the request's tenant context.
# ---------------------------------------------------------------------------


def test_org_mismatch_403(sqlite_factory):
    with sqlite_factory() as session:
        key = _seed_app(session, delegate=True)
        other_ctx = TenantContext(org_id=uuid.uuid4())  # never equals the seeded app's org
        with pytest.raises(HTTPException) as exc:
            get_effective_principal(
                x_app_key=key,
                x_on_behalf_of_email="alice@example.com",
                session=session,
                principal=_BASE,
                ctx=other_ctx,
            )
        assert exc.value.status_code == 403


def test_org_match_allows_delegation(sqlite_factory):
    with sqlite_factory() as session:
        org = Organization(slug="o5", name="O5")
        session.add(org)
        session.flush()
        plaintext, key_hash = generate_app_key()
        app = ClientApp(
            org_id=org.id,
            slug="chat-agent",
            name="CA",
            api_key_hash=key_hash,
            can_delegate_identity=True,
        )
        session.add(app)
        session.commit()
        matching_ctx = TenantContext(org_id=org.id)
        p = get_effective_principal(
            x_app_key=plaintext,
            x_on_behalf_of_email="alice@example.com",
            session=session,
            principal=_BASE,
            ctx=matching_ctx,
        )
        assert p.kind == "user"
        assert p.user_id == "alice@example.com"
        assert p.verified is True
