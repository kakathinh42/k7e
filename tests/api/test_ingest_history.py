"""Tests for per-ingest token usage + cost recording."""

from __future__ import annotations

import uuid

from k7e_api.config import Settings
from k7e_api.ingest_history import estimate_cost_usd, record_ingest_run
from k7e_api.models import (
    IngestRun,
    Organization,
    RawDocument,
    Space,
    Team,
)


def _settings():
    return Settings(llm_cost_input_usd_per_mtok=3.0, llm_cost_output_usd_per_mtok=15.0)


def test_estimate_cost_usd_uses_per_mtok_rates():
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}
    assert estimate_cost_usd(usage, _settings()) == 18.0  # 1M*$3 + 1M*$15
    assert estimate_cost_usd({"prompt_tokens": 0, "completion_tokens": 0}, _settings()) == 0.0


def test_record_ingest_run_persists_tokens_cost_and_filename(sqlite_factory):
    with sqlite_factory() as s:
        rid = uuid.uuid4()
        s.add(
            RawDocument(
                id=rid,
                filename="meeting-notes.md",
                sha256="x" * 64,
                object_store_ref="raw/x",
                mime_type="text/markdown",
                size_bytes=10,
                source_system="manual_upload",
                source_external_id="ext",
            )
        )
        s.commit()

        run = record_ingest_run(
            s,
            raw_document_id=str(rid),
            source_slug="meeting-notes",
            page_count=4,
            usage={
                "prompt_tokens": 2000,
                "completion_tokens": 500,
                "total_tokens": 2500,
                "calls": 3,
            },
            model_id="wiki-default",
            settings=_settings(),
        )

        assert run.filename == "meeting-notes.md"  # pulled from RawDocument
        assert run.total_tokens == 2500 and run.llm_calls == 3
        assert run.page_count == 4
        # 2000*$3/M + 500*$15/M = 0.006 + 0.0075 = 0.0135
        assert run.cost_usd == 0.0135
        # RawDocument has no org_id set → doc found but org_id is None
        assert run.org_id is None

    with sqlite_factory() as s:
        assert s.query(IngestRun).count() == 1


def test_record_ingest_run_tolerates_unknown_raw_document(sqlite_factory):
    with sqlite_factory() as s:
        run = record_ingest_run(
            s,
            raw_document_id="not-a-uuid",
            source_slug="x",
            page_count=1,
            usage={"prompt_tokens": 100, "completion_tokens": 0, "total_tokens": 100},
            model_id="wiki-default",
            settings=_settings(),
        )
        assert run.filename == "" and run.raw_document_id is None


def test_record_ingest_run_stamps_org_id_from_raw_document(sqlite_factory):
    """IngestRun.org_id is propagated from the RawDocument's org_id."""
    org_id = uuid.uuid4()
    with sqlite_factory() as s:
        rid = uuid.uuid4()
        s.add(
            RawDocument(
                id=rid,
                org_id=org_id,
                filename="report.pdf",
                sha256="a" * 64,
                object_store_ref="raw/a",
                mime_type="application/pdf",
                size_bytes=42,
                source_system="manual_upload",
                source_external_id="ext-org",
            )
        )
        s.commit()

        run = record_ingest_run(
            s,
            raw_document_id=str(rid),
            source_slug="report",
            page_count=2,
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            model_id="wiki-default",
            settings=_settings(),
        )

        assert run.org_id == org_id, "IngestRun must carry the org_id from its RawDocument"


def test_record_ingest_run_org_id_is_none_when_no_raw_document(sqlite_factory):
    """IngestRun.org_id is None when the raw_document_id resolves to nothing."""
    with sqlite_factory() as s:
        run = record_ingest_run(
            s,
            raw_document_id=None,
            source_slug="slug",
            page_count=1,
            usage={"prompt_tokens": 10, "completion_tokens": 0, "total_tokens": 10},
            model_id="wiki-default",
            settings=_settings(),
        )
        assert run.org_id is None


def _run_for_space(session, *, space_id, filename: str) -> None:
    """Seed a RawDocument (in ``space_id``) + its IngestRun."""
    rid = uuid.uuid4()
    session.add(
        RawDocument(
            id=rid,
            filename=filename,
            sha256=uuid.uuid4().hex * 2,
            object_store_ref=f"raw/{rid}",
            mime_type="text/markdown",
            size_bytes=10,
            source_system="manual_upload",
            source_external_id=str(rid),
            space_id=space_id,
        )
    )
    session.add(
        IngestRun(
            raw_document_id=rid,
            filename=filename,
            source_slug=filename.removesuffix(".md"),
            model_id="wiki-default",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            llm_calls=1,
            cost_usd=0.001,
            page_count=1,
        )
    )
    session.commit()


def test_history_endpoint_reports_space_kind(api_client, sqlite_factory):
    """GET /ingest/history annotates each run with its space (private/team/public)."""
    org_id = uuid.uuid4()
    public_id, team_space_id, personal_id = (uuid.uuid4() for _ in range(3))
    with sqlite_factory() as s:
        s.add(Organization(id=org_id, slug="org", name="Org"))
        s.add(Space(id=public_id, org_id=org_id, slug="engineering", name="Public"))
        s.add(Space(id=team_space_id, org_id=org_id, slug="acme", name="Acme"))
        s.add(
            Space(
                id=personal_id,
                org_id=org_id,
                slug="user-me",
                name="My Space",
                owner_user_id="me",
            )
        )
        s.add(
            Team(
                org_id=org_id,
                space_id=team_space_id,
                slug="acme",
                name="Acme",
                created_by="me",
            )
        )
        s.commit()
        _run_for_space(s, space_id=public_id, filename="public-doc.md")
        _run_for_space(s, space_id=team_space_id, filename="team-doc.md")
        _run_for_space(s, space_id=personal_id, filename="private-doc.md")
        # A run whose raw document has no space → space is None (legacy).
        s.add(
            IngestRun(
                raw_document_id=None,
                filename="orphan.md",
                source_slug="orphan",
                model_id="wiki-default",
                prompt_tokens=1,
                completion_tokens=0,
                total_tokens=1,
                llm_calls=1,
                cost_usd=0.0,
                page_count=1,
            )
        )
        s.commit()

    rows = api_client.get("/ingest/history").json()
    kind_by_file = {r["filename"]: (r["space"] or {}).get("kind") for r in rows}
    assert kind_by_file["public-doc.md"] == "public"
    assert kind_by_file["team-doc.md"] == "team"
    assert kind_by_file["private-doc.md"] == "personal"
    assert kind_by_file["orphan.md"] is None
