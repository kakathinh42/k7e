"""Postgres-only migration round-trip: 0020 knowledge_items.domain + item_tags.

Skipped unless WIKI_TEST_PG_DSN is set. Run manually against a THROWAWAY
database (this test tears the schema down to base — never point it at a DB whose
data you care about):

    createdb -U wiki wiki_m4test   # or: docker compose exec postgres createdb -U wiki wiki_m4test
    WIKI_TEST_PG_DSN=postgresql+psycopg://wiki:wiki@localhost:5435/wiki_m4test \\
        .venv/bin/python -m pytest tests/api/test_classification_migration.py -v

Verifies: upgrading 0019 -> 0020 adds the ``domain`` column + ``ix_knowledge_items_domain``
and the ``item_tags`` table with its three indexes + ``uq_item_tag``; downgrading
0020 -> 0019 removes all of them; and re-upgrading is clean.
"""

from __future__ import annotations

import os
import uuid

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

_DSN = os.environ.get("WIKI_TEST_PG_DSN")
pytestmark = pytest.mark.skipif(not _DSN, reason="WIKI_TEST_PG_DSN not set")

# 0016's seeded default org (so tenant-scoped FKs are satisfiable).
_ORG_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")

_ALEMBIC_INI = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api", "alembic.ini")
)
_ALEMBIC_DIR = os.path.dirname(_ALEMBIC_INI)


def _alembic_cfg(dsn: str) -> AlembicConfig:
    cfg = AlembicConfig(_ALEMBIC_INI)
    cfg.set_main_option("sqlalchemy.url", dsn)
    cfg.set_main_option("script_location", os.path.join(_ALEMBIC_DIR, "alembic"))
    return cfg


def _table_exists(conn, table: str) -> bool:
    return bool(
        conn.execute(text("SELECT to_regclass(:t) IS NOT NULL"), {"t": f"public.{table}"}).scalar()
    )


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


def _unique_constraints(conn, table: str) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid=to_regclass(:t) AND contype='u' ORDER BY 1"
            ),
            {"t": f"public.{table}"},
        )
    ]


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


def _teardown(engine: sa.Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS item_tags CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS memberships CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS teams CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS ingest_runs CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS wiki_links CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS claim_clusters CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS claims CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS source_page_links CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS wiki_chunks CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS gate_decisions CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS review_tasks CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS knowledge_item_versions CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS knowledge_items CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS raw_documents CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS sources CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS role_grants CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS projects CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS spaces CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS organizations CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS alembic_version CASCADE"))


_ITEM_TAGS_INDEXES = {
    "ix_item_tags_org_id",
    "ix_item_tags_item_id",
    "ix_item_tags_tag",
}


def test_0020_classification_round_trip() -> None:
    assert _DSN, "WIKI_TEST_PG_DSN must be set"
    from k7e_api.config import get_settings

    _prev = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = _DSN
    get_settings.cache_clear()
    engine = sa.create_engine(_DSN, poolclass=sa.pool.NullPool)
    cfg = _alembic_cfg(_DSN)
    try:
        _teardown(engine)

        # Build at 0019 (knowledge_items exists, without a domain column).
        alembic_command.upgrade(cfg, "0019_teams_membership")
        with engine.connect() as conn:
            assert "domain" not in _columns(conn, "knowledge_items")
            assert not _table_exists(conn, "item_tags")

        # Upgrade to 0020.
        alembic_command.upgrade(cfg, "0020_classification")
        with engine.connect() as conn:
            assert "domain" in _columns(conn, "knowledge_items"), "domain column missing"
            assert "ix_knowledge_items_domain" in _indexes(conn, "knowledge_items")
            assert _table_exists(conn, "item_tags"), "item_tags must exist after 0020"
            assert _ITEM_TAGS_INDEXES.issubset(set(_indexes(conn, "item_tags")))
            assert "uq_item_tag" in _unique_constraints(conn, "item_tags")

        # Downgrade to 0019 — everything 0020 added is gone.
        alembic_command.downgrade(cfg, "0019_teams_membership")
        with engine.connect() as conn:
            assert "domain" not in _columns(conn, "knowledge_items")
            assert "ix_knowledge_items_domain" not in _indexes(conn, "knowledge_items")
            assert not _table_exists(conn, "item_tags")

        # Re-upgrade — clean.
        alembic_command.upgrade(cfg, "0020_classification")
        with engine.connect() as conn:
            assert "domain" in _columns(conn, "knowledge_items")
            assert _table_exists(conn, "item_tags")

        alembic_command.downgrade(cfg, "base")
    finally:
        if _prev is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = _prev
        get_settings.cache_clear()
        engine.dispose()
