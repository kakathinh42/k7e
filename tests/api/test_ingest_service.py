import hashlib

import pytest
from k7e_api.connectors.base import FetchedDocument
from k7e_api.ingest_service import ingest_document
from k7e_api.models import Base, RawDocument
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker


class _FakeStore:
    def put(self, key, data):
        return f"mem://{key}"


@pytest.fixture
def session():
    eng = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(eng)
    yield sessionmaker(bind=eng, expire_on_commit=False)()


def _doc(content=b"# Hello"):
    return FetchedDocument(
        source_system="filesystem",
        source_external_id="a.md",
        source_tier="A",
        filename="a.md",
        content=content,
        content_type="text/markdown",
    )


def test_first_ingest_creates_rawdoc_and_starts_workflow(session):
    started = []
    res = ingest_document(session, _FakeStore(), lambda rid: started.append(rid) or "wf-1", _doc())
    assert res["status"] == "ingested"
    assert len(started) == 1
    n = session.execute(select(func.count()).select_from(RawDocument)).scalar_one()
    assert n == 1
    row = session.execute(select(RawDocument)).scalars().one()
    assert row.source_system == "filesystem"
    assert row.source_external_id == "a.md"
    assert row.sha256 == hashlib.sha256(b"# Hello").hexdigest()


def test_reingest_unchanged_is_skipped(session):
    store, starter = _FakeStore(), lambda rid: "wf"
    ingest_document(session, store, starter, _doc())
    res2 = ingest_document(session, store, starter, _doc())
    assert res2["status"] == "skipped"
    n = session.execute(select(func.count()).select_from(RawDocument)).scalar_one()
    assert n == 1  # no duplicate row


def test_reingest_changed_content_ingests_again(session):
    store, starter = _FakeStore(), lambda rid: "wf"
    ingest_document(session, store, starter, _doc(b"v1"))
    res2 = ingest_document(session, store, starter, _doc(b"v2 changed"))
    assert res2["status"] == "ingested"
    n = session.execute(select(func.count()).select_from(RawDocument)).scalar_one()
    assert n == 2


def test_run_connector_ingests_then_skips_on_rerun(session, tmp_path):
    from k7e_api.connectors.filesystem import FilesystemConnector
    from k7e_api.ingest_service import run_connector

    (tmp_path / "a.md").write_text("# Alpha")
    (tmp_path / "b.md").write_text("# Beta")
    conn = FilesystemConnector(root=str(tmp_path), patterns=["*.md"])
    store, starter = _FakeStore(), lambda rid: "wf"

    first = run_connector(session, store, starter, conn)
    assert first == {"connector": "filesystem", "ingested": 2, "skipped": 0}

    second = run_connector(session, store, starter, conn)
    assert second["ingested"] == 0 and second["skipped"] == 2

    (tmp_path / "a.md").write_text("# Alpha v2")
    third = run_connector(session, store, starter, conn)
    assert third["ingested"] == 1 and third["skipped"] == 1


def test_run_connector_stamps_org_and_allowed_groups(session):
    import uuid

    from k7e_api.ingest_service import run_connector
    from k7e_api.models import RawDocument

    org = uuid.uuid4()

    class _OneDoc:
        name = "fake"

        def fetch(self):
            yield _doc(b"# Page")

    run_connector(
        session,
        _FakeStore(),
        lambda rid: "wf",
        _OneDoc(),
        org_id=org,
        allowed_groups=["g1", "g2"],
    )
    row = session.execute(select(RawDocument)).scalars().one()
    assert row.org_id == org
    assert row.allowed_groups == ["g1", "g2"]


def test_ingest_document_records_and_returns_workflow_id(session):
    from k7e_api.ingest_service import ingest_document
    from k7e_api.models import RawDocument

    res = ingest_document(session, _FakeStore(), lambda rid: "wf-42", _doc(b"# X"))
    assert res["status"] == "ingested"
    assert res["workflow_id"] == "wf-42"
    row = session.execute(select(RawDocument)).scalars().one()
    assert row.workflow_id == "wf-42"


def test_as_sync_workflow_starter_runs_async(session):
    from k7e_api.ingest_service import as_sync_workflow_starter

    async def _astart(rid):
        return "wf-async"

    sync = as_sync_workflow_starter(_astart)
    assert sync("r1") == "wf-async"  # sync context: asyncio.run works


def test_ingest_document_stamps_space_id_and_created_by(session):
    import uuid

    space_id = uuid.uuid4()
    res = ingest_document(
        session,
        _FakeStore(),
        lambda rid: "wf-space",
        _doc(b"# Personal"),
        space_id=space_id,
        created_by="alice",
    )
    assert res["status"] == "ingested"
    row = session.execute(select(RawDocument)).scalars().one()
    assert row.space_id == space_id
    assert row.created_by == "alice"


def test_ingest_document_without_space_or_creator_is_legacy_null(session):
    ingest_document(session, _FakeStore(), lambda rid: "wf-legacy", _doc(b"# Legacy"))
    row = session.execute(select(RawDocument)).scalars().one()
    assert row.space_id is None
    assert row.created_by is None
