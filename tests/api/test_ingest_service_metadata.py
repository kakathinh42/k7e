"""M3 Step C: ingest seam carries extra_metadata + returns existing id on skip."""

from __future__ import annotations

from k7e_api.connectors.base import FetchedDocument
from k7e_api.ingest_service import ingest_document
from k7e_api.models import RawDocument
from sqlalchemy import select


class _FakeStore:
    def put(self, key, data):
        return f"mem://{key}"


def _doc(content=b"hello", meta=None):
    return FetchedDocument(
        source_system="chat_agent",
        source_external_id="t1",
        source_tier="B",
        filename="c.md",
        content=content,
        content_type="text/markdown",
        extra_metadata=meta,
    )


def test_ingest_document_persists_extra_metadata(sqlite_factory):
    with sqlite_factory() as s:
        meta = {"participants": ["a"], "captured_at": "2026-07-06T00:00:00+00:00"}
        res = ingest_document(
            s,
            _FakeStore(),
            lambda rid: "wf",
            _doc(meta=meta),
            org_id=None,
            allowed_groups=["team:eng"],
        )
        assert res["status"] == "ingested"
        row = s.execute(select(RawDocument)).scalars().one()
        assert row.extra_metadata == meta
        assert row.allowed_groups == ["team:eng"]


def test_idempotent_skip_returns_existing_id(sqlite_factory):
    with sqlite_factory() as s:
        r1 = ingest_document(s, _FakeStore(), lambda rid: "wf-1", _doc())
        r2 = ingest_document(s, _FakeStore(), lambda rid: "wf-2", _doc())
        assert r2["status"] == "skipped"
        assert r2["raw_document_id"] == r1["raw_document_id"]
        assert r2["workflow_id"] == "wf-1"


def test_idempotency_is_org_scoped(sqlite_factory):
    import uuid

    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    with sqlite_factory() as s:
        r1 = ingest_document(s, _FakeStore(), lambda rid: "wf-a", _doc(), org_id=org_a)
        r2 = ingest_document(s, _FakeStore(), lambda rid: "wf-b", _doc(), org_id=org_b)
        # Same (source_system, external_id, content) but different orgs → the
        # second must NOT be deduped against the first tenant's document.
        assert r1["status"] == "ingested"
        assert r2["status"] == "ingested"
        assert len(s.execute(select(RawDocument)).scalars().all()) == 2
