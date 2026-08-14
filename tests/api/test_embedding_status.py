"""GET /ingest/embedding-status reports corpus-wide chunk embedding progress."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from k7e_api.models import (
    KnowledgeItem,
    KnowledgeItemVersion,
    Organization,
    Space,
    Team,
    WikiChunk,
)


def _seed_chunks(session, *, embedded: int, pending: int) -> None:
    item = KnowledgeItem(slug="s", type="source", title="S", status="published")
    session.add(item)
    session.flush()
    ver = KnowledgeItemVersion(
        item_id=item.id,
        version_number=1,
        markdown_body="body",
        model_id="m",
        created_by="t",
        status="published",
        title="S",
        citations=[],
    )
    session.add(ver)
    session.flush()
    idx = 0
    for _ in range(embedded):
        session.add(
            WikiChunk(
                item_id=item.id,
                version_id=ver.id,
                chunk_index=idx,
                chunk_text="c",
                embedding=[0.1, 0.2],
            )
        )
        idx += 1
    for _ in range(pending):
        session.add(
            WikiChunk(
                item_id=item.id,
                version_id=ver.id,
                chunk_index=idx,
                chunk_text="c",
                embedding=None,
            )
        )
        idx += 1
    session.commit()


def test_embedding_status_counts_embedded_and_pending(api_client, sqlite_factory):
    with sqlite_factory() as s:
        _seed_chunks(s, embedded=2, pending=1)

    resp = api_client.get("/ingest/embedding-status")
    assert resp.status_code == 200
    assert resp.json() == {"total": 3, "embedded": 2, "pending": 1}


def test_embedding_status_all_embedded(api_client, sqlite_factory):
    with sqlite_factory() as s:
        _seed_chunks(s, embedded=4, pending=0)

    body = api_client.get("/ingest/embedding-status").json()
    assert body == {"total": 4, "embedded": 4, "pending": 0}


def test_embedding_status_empty_corpus(api_client):
    body = api_client.get("/ingest/embedding-status").json()
    assert body == {"total": 0, "embedded": 0, "pending": 0}


def _seed_space_chunks(session, *, space_id, n: int, created_at=None) -> None:
    """Seed ``n`` embedded chunks whose page lives in ``space_id``."""
    item = KnowledgeItem(
        slug=f"s-{uuid.uuid4().hex}",
        type="source",
        title="S",
        status="published",
        space_id=space_id,
    )
    session.add(item)
    session.flush()
    ver = KnowledgeItemVersion(
        item_id=item.id,
        version_number=1,
        markdown_body="body",
        model_id="m",
        created_by="t",
        status="published",
        title="S",
        citations=[],
    )
    session.add(ver)
    session.flush()
    for idx in range(n):
        kwargs = {}
        if created_at is not None:
            kwargs["created_at"] = created_at
        session.add(
            WikiChunk(
                item_id=item.id,
                version_id=ver.id,
                chunk_index=idx,
                chunk_text="c",
                embedding=[0.1, 0.2],
                **kwargs,
            )
        )
    session.commit()


def test_embedding_status_scoped_by_space_kind(api_client, sqlite_factory):
    """?space_kind= narrows to chunks whose page lives in that kind of space."""
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
                name="Me",
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
        _seed_space_chunks(s, space_id=public_id, n=3)
        _seed_space_chunks(s, space_id=team_space_id, n=2)
        _seed_space_chunks(s, space_id=personal_id, n=1)

    assert api_client.get("/ingest/embedding-status").json()["total"] == 6
    assert api_client.get("/ingest/embedding-status?space_kind=team").json() == {
        "total": 2,
        "embedded": 2,
        "pending": 0,
    }
    assert api_client.get("/ingest/embedding-status?space_kind=personal").json()["total"] == 1
    assert api_client.get("/ingest/embedding-status?space_kind=public").json()["total"] == 3


def test_embedding_status_scoped_by_month_and_year(api_client, sqlite_factory):
    """?year=&month= narrows to chunks created in that month."""
    org_id = uuid.uuid4()
    sid = uuid.uuid4()
    with sqlite_factory() as s:
        s.add(Organization(id=org_id, slug="org", name="Org"))
        s.add(Space(id=sid, org_id=org_id, slug="engineering", name="Public"))
        s.commit()
        _seed_space_chunks(
            s, space_id=sid, n=2, created_at=datetime(2026, 7, 15, tzinfo=timezone.utc)
        )
        _seed_space_chunks(
            s, space_id=sid, n=3, created_at=datetime(2026, 6, 10, tzinfo=timezone.utc)
        )

    assert api_client.get("/ingest/embedding-status?year=2026&month=7").json()["total"] == 2
    assert api_client.get("/ingest/embedding-status?year=2026&month=6").json()["total"] == 3
    assert api_client.get("/ingest/embedding-status?year=2025").json()["total"] == 0
