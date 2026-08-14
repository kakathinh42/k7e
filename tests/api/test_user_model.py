"""User model — native email+password accounts (PAT SSO Phase 1, Task 1)."""

from __future__ import annotations

import pytest
from k7e_api.models import Organization, User
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from tests.api.conftest import TEST_TENANT_CONTEXT

_ORG = TEST_TENANT_CONTEXT.org_id


def _seed_org(s) -> None:
    if s.get(Organization, _ORG) is None:
        s.add(Organization(id=_ORG, slug="test-org", name="Test Org"))
        s.commit()


def test_user_persists(sqlite_factory):
    with sqlite_factory() as s:
        _seed_org(s)
        s.add(User(email="alice@example.com", password_hash="hash", org_id=_ORG))
        s.commit()
        u = s.execute(select(User).where(User.email == "alice@example.com")).scalar_one()
        assert u.id is not None
        assert u.org_id == _ORG
        assert u.password_hash == "hash"
        assert u.created_at is not None


def test_user_email_unique(sqlite_factory):
    with sqlite_factory() as s:
        _seed_org(s)
        s.add(User(email="bob@example.com", password_hash="a", org_id=_ORG))
        s.commit()
        s.add(User(email="bob@example.com", password_hash="b", org_id=_ORG))
        with pytest.raises(IntegrityError):
            s.commit()
