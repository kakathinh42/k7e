"""Shared fixtures for worker tests: an isolated in-memory SQLite DB.

Worker tests need the same per-test SQLite ``sessionmaker`` the API tests use,
but not the API conftest's RBAC ``before_flush`` seeding (that is a read-path
concern for the API suite). This is a minimal, standalone factory.
"""

from __future__ import annotations

import pytest
from k7e_api.models import Base
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker


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
