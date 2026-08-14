"""Migration 0024: personal-space columns + one-personal-space-per-user index.

The SQLite tests exercise the model-level schema (Base.metadata.create_all,
including the partial unique index via sqlite_where). The Postgres-only
migration round-trip is skipped unless WIKI_TEST_PG_DSN is set. Run manually:

    WIKI_TEST_PG_DSN=postgresql+psycopg://wiki:wiki@localhost:5435/wiki \\
        .venv/bin/python -m pytest tests/api/test_personal_space_migration.py -v
"""

from __future__ import annotations

import os

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from k7e_api.models import Organization, RawDocument, Space
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

_DSN = os.environ.get("WIKI_TEST_PG_DSN")

_ALEMBIC_INI = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api", "alembic.ini")
)
_ALEMBIC_DIR = os.path.dirname(_ALEMBIC_INI)


def test_columns_exist(sqlite_factory):
    with sqlite_factory() as session:
        org = Organization(slug="o", name="O")
        session.add(org)
        session.flush()
        sp = Space(org_id=org.id, slug="user-alice", name="alice", owner_user_id="alice")
        session.add(sp)
        session.flush()
        raw = RawDocument(
            filename="f.md",
            sha256="0" * 64,
            object_store_ref="r",
            mime_type="text/markdown",
            size_bytes=1,
            space_id=sp.id,
            created_by="alice",
        )
        session.add(raw)
        session.commit()
        assert raw.space_id == sp.id and sp.owner_user_id == "alice"


def test_second_personal_space_same_owner_rejected(sqlite_factory):
    with sqlite_factory() as session:
        org = Organization(slug="o2", name="O2")
        session.add(org)
        session.flush()
        session.add(Space(org_id=org.id, slug="user-a", name="a", owner_user_id="a"))
        session.flush()
        session.add(Space(org_id=org.id, slug="user-a-2", name="a", owner_user_id="a"))
        with pytest.raises(IntegrityError):
            session.flush()


def test_two_non_personal_spaces_fine(sqlite_factory):
    # NULL owner_user_id must not collide under the partial unique index.
    with sqlite_factory() as session:
        org = Organization(slug="o3", name="O3")
        session.add(org)
        session.flush()
        session.add(Space(org_id=org.id, slug="s1", name="s1"))
        session.add(Space(org_id=org.id, slug="s2", name="s2"))
        session.commit()


def test_same_owner_different_orgs_fine(sqlite_factory):
    # The unique index is compound (org_id, owner_user_id): the same user may
    # own one personal space in each org.
    with sqlite_factory() as session:
        o1 = Organization(slug="o4", name="O4")
        o2 = Organization(slug="o5", name="O5")
        session.add_all([o1, o2])
        session.flush()
        session.add(Space(org_id=o1.id, slug="user-a", name="a", owner_user_id="a"))
        session.add(Space(org_id=o2.id, slug="user-a", name="a", owner_user_id="a"))
        session.commit()


# ---------------------------------------------------------------------------
# Postgres-only migration round-trip (house pattern: test_team_migration.py).
# ---------------------------------------------------------------------------


def _alembic_cfg(dsn: str) -> AlembicConfig:
    cfg = AlembicConfig(_ALEMBIC_INI)
    cfg.set_main_option("sqlalchemy.url", dsn)
    cfg.set_main_option("script_location", os.path.join(_ALEMBIC_DIR, "alembic"))
    return cfg


def _columns(conn, table: str) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=:t ORDER BY 1"
            ),
            {"t": table},
        )
    ]


def _indexes(conn, table: str) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname='public' AND tablename=:t ORDER BY 1"
            ),
            {"t": table},
        )
    ]


def _uq_space_org_owner_def(conn) -> str | None:
    return conn.execute(
        text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE schemaname='public' AND indexname='uq_space_org_owner'"
        )
    ).scalar()


def _teardown(engine: sa.Engine) -> None:
    with engine.begin() as conn:
        for table in (
            "memberships",
            "teams",
            "client_apps",
            "item_tags",
            "ingest_runs",
            "wiki_links",
            "claim_clusters",
            "claims",
            "source_page_links",
            "wiki_chunks",
            "gate_decisions",
            "review_tasks",
            "knowledge_item_versions",
            "knowledge_items",
            "raw_documents",
            "sources",
            "role_grants",
            "projects",
            "spaces",
            "organizations",
            "alembic_version",
        ):
            conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))


@pytest.mark.skipif(not _DSN, reason="WIKI_TEST_PG_DSN not set")
def test_0024_personal_space_cols_round_trip() -> None:
    assert _DSN, "WIKI_TEST_PG_DSN must be set"
    from k7e_api.config import get_settings

    _prev = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = _DSN
    get_settings.cache_clear()
    engine = sa.create_engine(_DSN, poolclass=sa.pool.NullPool)
    cfg = _alembic_cfg(_DSN)
    try:
        _teardown(engine)

        # Build everything up to head (includes 0024).
        alembic_command.upgrade(cfg, "head")
        with engine.connect() as conn:
            assert "owner_user_id" in _columns(conn, "spaces")
            assert "space_id" in _columns(conn, "raw_documents")
            assert "created_by" in _columns(conn, "raw_documents")
            assert "ix_raw_documents_space_id" in _indexes(conn, "raw_documents")
            indexdef = _uq_space_org_owner_def(conn)
            assert indexdef is not None, "uq_space_org_owner missing after upgrade"
            assert "UNIQUE" in indexdef, indexdef
            assert "WHERE (owner_user_id IS NOT NULL)" in indexdef, indexdef

        # Downgrade to 0023 — all 0024 objects gone.
        alembic_command.downgrade(cfg, "0023_chunk_pending_embed_idx")
        with engine.connect() as conn:
            assert "owner_user_id" not in _columns(conn, "spaces")
            assert "space_id" not in _columns(conn, "raw_documents")
            assert "created_by" not in _columns(conn, "raw_documents")
            assert "ix_raw_documents_space_id" not in _indexes(conn, "raw_documents")
            assert _uq_space_org_owner_def(conn) is None

        # Re-upgrade — clean.
        alembic_command.upgrade(cfg, "head")
        with engine.connect() as conn:
            assert "owner_user_id" in _columns(conn, "spaces")
            assert "space_id" in _columns(conn, "raw_documents")
            assert "created_by" in _columns(conn, "raw_documents")
            assert _uq_space_org_owner_def(conn) is not None
    finally:
        if _prev is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = _prev
        get_settings.cache_clear()
        engine.dispose()
