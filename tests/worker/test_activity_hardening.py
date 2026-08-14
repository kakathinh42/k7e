import uuid

import pytest
from k7e_api.models import Base
from k7e_worker import activities
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker
from temporalio.exceptions import ApplicationError


@pytest.fixture()
def worker_sqlite_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False, class_=Session)
    Base.metadata.drop_all(engine)
    engine.dispose()


async def test_missing_raw_document_is_non_retryable(monkeypatch, worker_sqlite_factory):
    monkeypatch.setattr(activities, "session_factory", worker_sqlite_factory)
    with pytest.raises(ApplicationError) as ei:
        await activities.load_raw_document(str(uuid.uuid4()))
    assert ei.value.non_retryable is True


def test_log_context_silent_outside_worker(monkeypatch):
    def raise_runtime():
        raise RuntimeError("no activity context")

    warnings: list = []
    monkeypatch.setattr(activities.activity, "info", raise_runtime)
    monkeypatch.setattr(activities.logger, "warning", lambda *a, **k: warnings.append(1))
    activities._activity_log_context("e", "load_raw_document")
    assert warnings == []


def test_log_context_warns_on_unexpected(monkeypatch):
    def raise_value():
        raise ValueError("unexpected")

    warnings: list = []
    monkeypatch.setattr(activities.activity, "info", raise_value)
    monkeypatch.setattr(activities.logger, "warning", lambda *a, **k: warnings.append(1))
    activities._activity_log_context("e", "load_raw_document")
    assert warnings == [1]
