"""Postgres-only migration round-trip: 0017 role_grants table + viewer seed.

Skipped unless WIKI_TEST_PG_DSN points at a Postgres instance that can host a
temporary test database (the same DSN used for the 0016 round-trip works fine).

Run manually:
    WIKI_TEST_PG_DSN=postgresql+psycopg://wiki:wiki@localhost:5435/wiki \\
        .venv/bin/python -m pytest tests/api/test_rbac_migration.py -v

What this tests
---------------
1. Start at revision 0016 (no role_grants table yet).
2. Run ``upgrade`` to 0017.
3. Assert:
   (a) ``role_grants`` table exists.
   (b) Exactly one row is seeded — the behavior-preserving all-org viewer grant.
   (c) The seeded row's deterministic fields match: id = _GRANT_ID,
       principal_kind='group', principal_id='public', role='viewer',
       scope_kind='org', scope_id = 0016's _ORG_ID, created_at IS NOT NULL.
   (d) The two indexes (``ix_role_grant_principal``, ``ix_role_grant_scope``)
       and the unique constraint (``uq_role_grant``) exist.
4. Run the seed INSERT a second time directly — ``ON CONFLICT DO NOTHING`` on
   ``uq_role_grant`` must make it a no-op (still exactly one row, unchanged id).
5. Run ``downgrade`` back to 0016.
6. Assert ``role_grants`` is gone (table + indexes + constraint).
7. Run ``upgrade`` again to 0017 — re-running the migration reproduces the
   single seed row (idempotent re-upgrade after a clean downgrade).
8. Cleanup — downgrade to base.
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
# Deterministic UUIDs from the migration (must match 0017 exactly).
# _ORG_ID is 0016's seeded ``default`` org; _GRANT_ID is 0017's seed row id.
# ---------------------------------------------------------------------------

_ORG_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
_GRANT_ID = uuid.UUID("00000000-0000-0000-0000-0000000000c1")

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
    cfg.set_main_option("script_location", os.path.join(_ALEMBIC_DIR, "alembic"))
    return cfg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _table_exists(conn: sa.Connection, table: str) -> bool:
    row = conn.execute(
        text("SELECT to_regclass(:t) IS NOT NULL"),
        {"t": f"public.{table}"},
    ).scalar()
    return bool(row)


def _indexes(conn: sa.Connection, table: str) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = 'public' AND tablename = :t ORDER BY 1"
            ),
            {"t": table},
        )
    ]


def _unique_constraints(conn: sa.Connection, table: str) -> list[str]:
    # NOTE: use to_regclass(:t), not :t::regclass — SQLAlchemy's text() param
    # regex does not recognize ":name" when it is immediately followed by "::"
    # (the cast breaks the negative-lookahead), so the param would silently go
    # unbound. to_regclass() takes text and returns regclass, avoiding the cast.
    return [
        r[0]
        for r in conn.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = to_regclass(:t) AND contype = 'u' ORDER BY 1"
            ),
            {"t": f"public.{table}"},
        )
    ]


def _teardown(engine: sa.Engine) -> None:
    """Drop all wiki tables so the test always starts from a clean slate.

    role_grants has no FKs into other tables, so it is dropped first; the rest
    mirror the 0016 round-trip teardown in dependency order.
    """
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS role_grants CASCADE"))
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


def test_0017_role_grants_and_viewer_seed_round_trip() -> None:
    """Full round-trip: build at 0016, upgrade to 0017, verify seed + schema,
    exercise ON CONFLICT idempotency, downgrade to 0016, upgrade again."""
    assert _DSN, "WIKI_TEST_PG_DSN must be set (skip guard should have fired)"

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
        # 1. Build schema at 0016 (one step before 0017)
        # ------------------------------------------------------------------
        alembic_command.upgrade(cfg, "0016_tenant_columns_backfill")

        # Sanity: role_grants must NOT exist yet (we're at 0016)
        with engine.connect() as conn:
            assert not _table_exists(conn, "role_grants"), "role_grants should not exist at 0016"

        # ------------------------------------------------------------------
        # 2. Upgrade to 0017 (the migration under test)
        # ------------------------------------------------------------------
        alembic_command.upgrade(cfg, "0017_role_grants_and_viewer_seed")

        # ------------------------------------------------------------------
        # 3. Assert schema + seeded grant
        # ------------------------------------------------------------------
        with engine.connect() as conn:
            # (a) table exists
            assert _table_exists(conn, "role_grants"), "role_grants must exist after 0017"

            # (d) indexes + unique constraint
            idxs = _indexes(conn, "role_grants")
            assert "ix_role_grant_principal" in idxs, (
                "ix_role_grant_principal must exist after 0017"
            )
            assert "ix_role_grant_scope" in idxs, "ix_role_grant_scope must exist after 0017"
            uqs = _unique_constraints(conn, "role_grants")
            assert "uq_role_grant" in uqs, "uq_role_grant must exist after 0017"

            # (b)+(c) exactly one seeded row with the deterministic fields
            rows = conn.execute(
                text(
                    "SELECT id, principal_kind, principal_id, role, scope_kind, "
                    "scope_id, created_at FROM role_grants"
                )
            ).fetchall()
            assert len(rows) == 1, f"expected exactly one seeded grant, got {len(rows)}"
            row = rows[0]
            assert uuid.UUID(str(row[0])) == _GRANT_ID, "seeded grant id mismatch"
            assert row[1] == "group", "seeded principal_kind must be 'group'"
            assert row[2] == "public", "seeded principal_id must be 'public'"
            assert row[3] == "viewer", "seeded role must be 'viewer'"
            assert row[4] == "org", "seeded scope_kind must be 'org'"
            assert uuid.UUID(str(row[5])) == _ORG_ID, (
                "seeded scope_id must be 0016's default org id"
            )
            assert row[6] is not None, "seeded created_at must be non-null"

        # ------------------------------------------------------------------
        # 4. Idempotency — re-run the exact seed INSERT the migration runs;
        #    ON CONFLICT DO NOTHING on uq_role_grant must make it a no-op
        #    (still one row, unchanged id).
        # ------------------------------------------------------------------
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO role_grants "
                    "(id, principal_kind, principal_id, role, scope_kind, "
                    "scope_id, created_at) "
                    "VALUES (:id, 'group', 'public', 'viewer', 'org', :org_id, now()) "
                    "ON CONFLICT (principal_kind, principal_id, role, scope_kind, "
                    "scope_id) DO NOTHING"
                ),
                {"id": str(_GRANT_ID), "org_id": str(_ORG_ID)},
            )
        with engine.connect() as conn:
            count, seed_id = conn.execute(
                text(
                    "SELECT COUNT(*), (SELECT id FROM role_grants WHERE "
                    "principal_kind='group' AND principal_id='public' AND "
                    "role='viewer' AND scope_kind='org' AND scope_id=:o)"
                ),
                {"o": str(_ORG_ID)},
            ).fetchone()
            assert count == 1, f"re-running the seed must not duplicate; got {count} rows"
            assert uuid.UUID(str(seed_id)) == _GRANT_ID, (
                "re-running the seed must not replace the existing row's id"
            )

        # ------------------------------------------------------------------
        # 5. Downgrade back to 0016
        # ------------------------------------------------------------------
        alembic_command.downgrade(cfg, "0016_tenant_columns_backfill")

        with engine.connect() as conn:
            # Table + indexes + constraint all gone
            assert not _table_exists(conn, "role_grants"), (
                "role_grants should be dropped after downgrade to 0016"
            )
            assert _indexes(conn, "role_grants") == [], (
                "role_grants indexes should be gone after downgrade"
            )
            assert _unique_constraints(conn, "role_grants") == [], (
                "role_grants unique constraints should be gone after downgrade"
            )

        # ------------------------------------------------------------------
        # 6. Upgrade again — re-running the migration after a clean downgrade
        #    reproduces exactly one seed row (idempotent re-upgrade).
        # ------------------------------------------------------------------
        alembic_command.upgrade(cfg, "0017_role_grants_and_viewer_seed")

        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, principal_kind, principal_id, role, scope_kind, "
                    "scope_id FROM role_grants"
                )
            ).fetchall()
            assert len(rows) == 1, f"re-upgrade must seed exactly one row, got {len(rows)}"
            row = rows[0]
            assert uuid.UUID(str(row[0])) == _GRANT_ID
            assert row[1] == "group"
            assert row[2] == "public"
            assert row[3] == "viewer"
            assert row[4] == "org"
            assert uuid.UUID(str(row[5])) == _ORG_ID

        # ------------------------------------------------------------------
        # 7. Cleanup — downgrade to base so the DB is empty again
        # ------------------------------------------------------------------
        alembic_command.downgrade(cfg, "base")

    finally:
        if _prev_db_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = _prev_db_url
        get_settings.cache_clear()
        engine.dispose()
