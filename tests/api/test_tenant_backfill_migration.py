"""Postgres-only migration round-trip: 0016 tenant columns + backfill.

Skipped unless WIKI_TEST_PG_DSN points at a Postgres instance that can host
a temporary test database (the same DSN used for pgvector tests works fine).

Run manually:
    WIKI_TEST_PG_DSN=postgresql+psycopg://wiki:wiki@localhost:5435/wiki \\
        .venv/bin/python -m pytest tests/api/test_tenant_backfill_migration.py -v

What this tests
---------------
1. Start at revision 0015 (org/space/project tables exist, no FK columns yet).
2. Insert pre-existing KnowledgeItem and RawDocument rows (representing data
   in the system before the tenant migration).
3. Run ``upgrade`` to 0016.
4. Assert:
   (a) A ``default`` org with deterministic UUID 00000000-…-a1 exists.
   (b) An ``engineering`` space with deterministic UUID 00000000-…-b1 exists.
   (c) Every pre-existing KnowledgeItem has non-null org_id == default_org_id.
   (d) Every pre-existing KnowledgeItem has non-null space_id == engineering_space_id.
   (e) Every pre-existing RawDocument has non-null org_id == default_org_id.
5. Run ``downgrade`` back to 0015.
6. Assert org/space columns no longer exist on the tables (FK columns dropped).
7. Run ``upgrade`` again to 0016 — backfill is idempotent (deterministic UUIDs
   mean re-inserting the same org/space rows is safe via ON CONFLICT DO NOTHING).
"""

from __future__ import annotations

import os
import uuid

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

# ---------------------------------------------------------------------------
# Skip gate — must be set to a Postgres DSN
# ---------------------------------------------------------------------------

_DSN = os.environ.get("WIKI_TEST_PG_DSN")
pytestmark = pytest.mark.skipif(not _DSN, reason="WIKI_TEST_PG_DSN not set")

# ---------------------------------------------------------------------------
# Deterministic UUIDs from the migration (must match 0016 exactly)
# ---------------------------------------------------------------------------

_ORG_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
_SPACE_ID = uuid.UUID("00000000-0000-0000-0000-0000000000b1")

# ---------------------------------------------------------------------------
# Alembic config helper
# ---------------------------------------------------------------------------

_ALEMBIC_INI = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api", "alembic.ini")
)
_ALEMBIC_DIR = os.path.dirname(_ALEMBIC_INI)


def _alembic_cfg(dsn: str) -> AlembicConfig:
    """Return an AlembicConfig pointing at the test database.

    k7e_api's env.py calls ``get_settings()`` (lru_cached) and overrides
    sqlalchemy.url from the DATABASE_URL environment variable. The caller
    must ensure os.environ["DATABASE_URL"] == dsn and the settings cache is
    cleared before invoking alembic commands.
    """
    cfg = AlembicConfig(_ALEMBIC_INI)
    cfg.set_main_option("sqlalchemy.url", dsn)
    # Resolve script_location to an absolute path (alembic.ini uses relative "alembic")
    cfg.set_main_option("script_location", os.path.join(_ALEMBIC_DIR, "alembic"))
    return cfg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _column_exists(conn: sa.Connection, table: str, column: str) -> bool:
    """Return True if *column* exists in *table* (Postgres information_schema)."""
    row = conn.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).scalar()
    return bool(row)


def _teardown(engine: sa.Engine) -> None:
    """Drop all wiki tables so the test always starts from a clean slate."""
    with engine.begin() as conn:
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
        conn.execute(text("DROP TABLE IF EXISTS projects CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS spaces CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS organizations CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS alembic_version CASCADE"))


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


def test_0016_backfill_round_trip() -> None:
    """Full round-trip: build at 0015, insert rows, upgrade to 0016, verify backfill,
    downgrade to 0015, upgrade again (idempotency check)."""
    assert _DSN, "WIKI_TEST_PG_DSN must be set (skip guard should have fired)"

    # Patch DATABASE_URL so k7e_api.config.get_settings() returns the test DSN.
    # Alembic's env.py calls get_settings() (lru_cached) — we must clear the cache
    # and force-set the env var before running any alembic command.
    from k7e_api.config import get_settings

    _prev_db_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = _DSN
    get_settings.cache_clear()

    engine = sa.create_engine(_DSN, poolclass=sa.pool.NullPool)
    cfg = _alembic_cfg(_DSN)

    try:
        # ------------------------------------------------------------------
        # 0. Tear down any leftover state from a previous failed run
        # ------------------------------------------------------------------
        _teardown(engine)

        # ------------------------------------------------------------------
        # 1. Build schema at 0015 (one step before 0016)
        # ------------------------------------------------------------------
        alembic_command.upgrade(cfg, "0015_org_space_project")

        # Sanity: org_id column must NOT exist yet (we're at 0015)
        with engine.connect() as conn:
            assert not _column_exists(conn, "knowledge_items", "org_id"), (
                "org_id should not exist at 0015"
            )
            assert not _column_exists(conn, "raw_documents", "org_id"), (
                "org_id should not exist at 0015"
            )

        # ------------------------------------------------------------------
        # 2. Insert pre-existing rows (simulating content before the migration)
        # ------------------------------------------------------------------
        ki_id = uuid.uuid4()
        rd_id = uuid.uuid4()

        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO knowledge_items "
                    "(id, slug, title, status, type, created_at, updated_at) "
                    "VALUES (:id, :slug, :title, 'published', 'source', now(), now())"
                ),
                {
                    "id": ki_id,
                    "slug": "pre-existing-item",
                    "title": "Pre-existing Item",
                },
            )
            conn.execute(
                text(
                    "INSERT INTO raw_documents "
                    "(id, filename, sha256, object_store_ref, mime_type, "
                    "size_bytes, status, source_system, source_tier, authority_weight, "
                    "created_at) "
                    "VALUES (:id, :fn, :sha, :ref, 'text/plain', 42, "
                    "'done', 'manual_upload', 'A', 1.0, now())"
                ),
                {
                    "id": rd_id,
                    "fn": "pre-existing.txt",
                    "sha": "a" * 64,
                    "ref": "objects/pre-existing.txt",
                },
            )

        # ------------------------------------------------------------------
        # 3. Upgrade to 0016 (the migration under test)
        # ------------------------------------------------------------------
        alembic_command.upgrade(cfg, "0016_tenant_columns_backfill")

        # ------------------------------------------------------------------
        # 4. Assert backfill outcomes
        # ------------------------------------------------------------------
        with engine.connect() as conn:
            # (a) default org exists with the deterministic UUID
            org_row = conn.execute(
                text("SELECT id, slug, name FROM organizations WHERE id = :i"),
                {"i": _ORG_ID},
            ).fetchone()
            assert org_row is not None, "default org must exist after 0016"
            assert org_row.slug == "default"
            assert org_row.name == "Default"

            # (b) engineering space exists with the deterministic UUID
            space_row = conn.execute(
                text("SELECT id, org_id, slug, name FROM spaces WHERE id = :i"),
                {"i": _SPACE_ID},
            ).fetchone()
            assert space_row is not None, "engineering space must exist after 0016"
            assert space_row.slug == "engineering"
            assert space_row.name == "Engineering"
            assert uuid.UUID(str(space_row.org_id)) == _ORG_ID

            # (c) pre-existing KnowledgeItem has non-null org_id pointing at default
            ki_row = conn.execute(
                text("SELECT org_id, space_id FROM knowledge_items WHERE id = :i"),
                {"i": ki_id},
            ).fetchone()
            assert ki_row is not None
            assert ki_row.org_id is not None, (
                "knowledge_item.org_id must be non-null after backfill"
            )
            assert uuid.UUID(str(ki_row.org_id)) == _ORG_ID, (
                "knowledge_item.org_id must point at default"
            )

            # (d) pre-existing KnowledgeItem has non-null space_id pointing at engineering
            assert ki_row.space_id is not None, (
                "knowledge_item.space_id must be non-null after backfill"
            )
            assert uuid.UUID(str(ki_row.space_id)) == _SPACE_ID, (
                "knowledge_item.space_id must point at engineering"
            )

            # (e) pre-existing RawDocument has non-null org_id pointing at default
            rd_row = conn.execute(
                text("SELECT org_id FROM raw_documents WHERE id = :i"),
                {"i": rd_id},
            ).fetchone()
            assert rd_row is not None
            assert rd_row.org_id is not None, "raw_document.org_id must be non-null after backfill"
            assert uuid.UUID(str(rd_row.org_id)) == _ORG_ID, (
                "raw_document.org_id must point at default"
            )

            # (f) org_id columns exist on all tenant-scoped tables
            for tbl in (
                "knowledge_items",
                "raw_documents",
                "wiki_chunks",
                "wiki_links",
                "sources",
                "review_tasks",
                "gate_decisions",
                "ingest_runs",
                "claims",
                "claim_clusters",
                "source_page_links",
            ):
                assert _column_exists(conn, tbl, "org_id"), f"{tbl}.org_id must exist after 0016"

            # (g) space_id + project_id exist on knowledge_items
            assert _column_exists(conn, "knowledge_items", "space_id"), (
                "knowledge_items.space_id must exist after 0016"
            )
            assert _column_exists(conn, "knowledge_items", "project_id"), (
                "knowledge_items.project_id must exist after 0016"
            )

        # ------------------------------------------------------------------
        # 5. Downgrade back to 0015
        # ------------------------------------------------------------------
        alembic_command.downgrade(cfg, "0015_org_space_project")

        with engine.connect() as conn:
            # After downgrade: org_id must be gone from tenant tables
            assert not _column_exists(conn, "knowledge_items", "org_id"), (
                "org_id should be dropped after downgrade to 0015"
            )
            assert not _column_exists(conn, "raw_documents", "org_id"), (
                "org_id should be dropped after downgrade to 0015"
            )

        # ------------------------------------------------------------------
        # 6. Upgrade again — idempotency check
        # ------------------------------------------------------------------
        alembic_command.upgrade(cfg, "0016_tenant_columns_backfill")

        with engine.connect() as conn:
            # Seeded org/space still exist (ON CONFLICT DO NOTHING on re-insert)
            org_row2 = conn.execute(
                text("SELECT id FROM organizations WHERE id = :i"), {"i": _ORG_ID}
            ).fetchone()
            assert org_row2 is not None, "default org must exist after re-upgrade"

            # Pre-existing rows are still backfilled (UPDATE WHERE org_id IS NULL is idempotent)
            ki_row2 = conn.execute(
                text("SELECT org_id, space_id FROM knowledge_items WHERE id = :i"),
                {"i": ki_id},
            ).fetchone()
            assert ki_row2 is not None
            assert uuid.UUID(str(ki_row2.org_id)) == _ORG_ID
            assert uuid.UUID(str(ki_row2.space_id)) == _SPACE_ID

        # ------------------------------------------------------------------
        # 7. Cleanup — downgrade to base so the DB is empty again
        # ------------------------------------------------------------------
        alembic_command.downgrade(cfg, "base")

    finally:
        # Restore DATABASE_URL and settings cache regardless of outcome
        if _prev_db_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = _prev_db_url
        get_settings.cache_clear()
        engine.dispose()
