import pytest
from k7e_api.identity import record_source_link, resolve_linked_item
from k7e_api.models import Base, KnowledgeItem
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def session():
    eng = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(eng)
    yield sessionmaker(bind=eng, expire_on_commit=False)()


def _item(session, slug="s"):
    it = KnowledgeItem(slug=slug, title="T", status="draft")
    session.add(it)
    session.flush()
    return it


def test_resolve_returns_none_when_no_link(session):
    assert resolve_linked_item(session, "confluence", "PAGE-1") is None


def test_record_then_resolve(session):
    it = _item(session)
    record_source_link(session, "confluence", "PAGE-1", it.id)
    session.flush()
    resolved = resolve_linked_item(session, "confluence", "PAGE-1")
    assert resolved is not None and resolved.id == it.id


def test_record_is_idempotent(session):
    it = _item(session)
    record_source_link(session, "confluence", "PAGE-1", it.id)
    record_source_link(session, "confluence", "PAGE-1", it.id)
    session.flush()
    assert resolve_linked_item(session, "confluence", "PAGE-1").id == it.id


def test_no_link_for_null_external_id(session):
    assert resolve_linked_item(session, "manual_upload", None) is None
