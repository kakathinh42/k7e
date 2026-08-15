"""Postgres-only migration round-trip: 0019 teams + memberships + spaces.visibility.

Skipped unless WIKI_TEST_PG_DSN is set. Run manually:

    WIKI_TEST_PG_DSN=postgresql+psycopg://wiki:wiki@localhost:5435/wiki \\
        .venv/bin/python -m pytest tests/api/test_team_migration.py -v

Verifies: tables + indexes + constraints created; existing spaces backfilled to
visibility='members'; downgrade drops everything; re-upgrade is clean.
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

# 0016's seeded default org (so the spaces FK is satisfiable).
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
        conn.execute(text("DROP TABLE IF EXISTS memberships CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS teams CASCADE"))
        # Note: spaces.visibility is dropped implicitly by the
        # ``DROP TABLE IF EXISTS spaces CASCADE`` below; an explicit
        # ``ALTER TABLE spaces DROP COLUMN`` here is not idempotent when the
        # spaces table doesn't exist (e.g. DB left at base by a prior
        # ``downgrade(base)``), so it is intentionally omitted.
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


def test_0019_teams_membership_round_trip() -> None:
    assert _DSN, "WIKI_TEST_PG_DSN must be set"
    from k7e_api.config import get_settings

    _prev = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = _DSN
    get_settings.cache_clear()
    engine = sa.create_engine(_DSN, poolclass=sa.pool.NullPool)
    cfg = _alembic_cfg(_DSN)
    try:
        _teardown(engine)

        # Build at 0018.
        alembic_command.upgrade(cfg, "0018_hot_read_indexes")

        # Insert a space at 0018 so we can verify the visibility backfill.
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO spaces (id, org_id, slug, name, default_language) "
                    "VALUES (:id, :org, 'preexist', 'Preexist', 'en')"
                ),
                {"id": str(uuid.uuid4()), "org": str(_ORG_ID)},
            )

        # Upgrade to 0019.
        alembic_command.upgrade(cfg, "0019_teams_membership")

        with engine.connect() as conn:
            assert _table_exists(conn, "teams"), "teams must exist after 0019"
            assert _table_exists(conn, "memberships"), "memberships must exist"
            assert "visibility" in _columns(conn, "spaces"), "visibility column missing"
            # Existing space backfilled to 'members' via server_default.
            vis = conn.execute(
                text("SELECT visibility FROM spaces WHERE slug='preexist'")
            ).scalar()
            assert vis == "members", f"existing space backfill expected 'members', got {vis!r}"
            # Indexes + constraints.
            assert "ix_teams_org_id" in _indexes(conn, "teams")
            assert "uq_team_org_slug" in _unique_constraints(conn, "teams")
            assert "uq_team_space" in _unique_constraints(conn, "teams")
            assert "ix_memberships_team_id" in _indexes(conn, "memberships")
            assert "ix_memberships_user_id" in _indexes(conn, "memberships")
            assert "uq_membership_team_user" in _unique_constraints(conn, "memberships")

        # Downgrade to 0018.
        alembic_command.downgrade(cfg, "0018_hot_read_indexes")
        with engine.connect() as conn:
            assert not _table_exists(conn, "teams"), "teams should be gone after downgrade"
            assert not _table_exists(conn, "memberships")
            assert "visibility" not in _columns(conn, "spaces")

        # Re-upgrade — clean.
        alembic_command.upgrade(cfg, "0019_teams_membership")
        with engine.connect() as conn:
            assert _table_exists(conn, "teams")
            assert _table_exists(conn, "memberships")
            assert "visibility" in _columns(conn, "spaces")

        # Clean up the test-inserted 'preexist' space before downgrading to base:
        # 0016's downgrade deletes the seeded default org, but this space still
        # references it via spaces_org_id_fkey (created by 0015, not dropped by
        # 0016's downgrade), which would otherwise raise a ForeignKeyViolation.
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM spaces WHERE slug='preexist'"))

        alembic_command.downgrade(cfg, "base")
    finally:
        if _prev is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = _prev
        get_settings.cache_clear()
        engine.dispose()
