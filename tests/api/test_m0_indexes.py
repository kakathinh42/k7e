"""M0 Task 1 — hot-read indexes exist on the declarative metadata.

The read/search path filters/joins on three columns that were previously
unindexed: ``knowledge_items.status`` (``status == 'published'`` on every
read/search), ``knowledge_items.current_version_id`` (joined on every read),
and ``wiki_chunks.item_id`` (joined whenever an item's chunks load). Migration
``0018`` adds single-column btree indexes on each.

These tests assert the indexes are declared on the ORM metadata (so
``Base.metadata.create_all`` builds them in SQLite tests) and that the
migration's upgrade/downgrade reference the same index names — guarding
against drift between ``models.py`` and ``0018_hot_read_indexes.py``.

A Postgres-gated round-trip (``WIKI_TEST_PG_DSN``) additionally exercises the
real migration: upgrade to 0018 builds the indexes, ``downgrade -1`` drops
them, and re-upgrade rebuilds them.
"""

from __future__ import annotations

import os

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from k7e_api.models import KnowledgeItem, WikiChunk
from sqlalchemy import inspect, text

# ---------------------------------------------------------------------------
# The three hot-read indexes added by migration 0018 (and index=True on the
# declarative columns). Names must match the migration exactly.
# ---------------------------------------------------------------------------

_EXPECTED_INDEXES: dict[str, set[str]] = {
    "knowledge_items": {
        "ix_knowledge_items_status",
        "ix_knowledge_items_current_version_id",
    },
    "wiki_chunks": {"ix_wiki_chunks_item_id"},
}


def _index_names(table) -> set[str]:
    return {idx.name for idx in table.indexes}


def test_index_declared_on_knowledge_item_metadata():
    """status + current_version_id carry index=True in the ORM metadata."""
    names = _index_names(KnowledgeItem.__table__)
    assert "ix_knowledge_items_status" in names, (
        "KnowledgeItem.status must be indexed (filtered on every read/search)"
    )
    assert "ix_knowledge_items_current_version_id" in names, (
        "KnowledgeItem.current_version_id must be indexed (joined on every read)"
    )


def test_index_declared_on_wiki_chunk_metadata():
    """wiki_chunks.item_id carries index=True in the ORM metadata."""
    names = _index_names(WikiChunk.__table__)
    assert "ix_wiki_chunks_item_id" in names, (
        "WikiChunk.item_id must be indexed (joined whenever chunks load)"
    )


def test_indexes_built_by_metadata_create_all(sqlite_factory):
    """Base.metadata.create_all (the SQLite test path) materializes all three.

    Inspects the live SQLite catalog via reflection so the assertion is against
    what the DB actually built, not just the declarative metadata.
    """
    with sqlite_factory() as session:
        insp = inspect(session.bind)
        for table, expected in _EXPECTED_INDEXES.items():
            built = {row["name"] for row in insp.get_indexes(table)}
            assert expected <= built, f"{table} missing indexes {expected - built}; built={built}"


# ---------------------------------------------------------------------------
# Postgres-gated Alembic round-trip (upgrade → downgrade -1 → upgrade).
# Skipped unless WIKI_TEST_PG_DSN points at a Postgres instance.
# ---------------------------------------------------------------------------

_DSN = os.environ.get("WIKI_TEST_PG_DSN")
_pg_only = pytest.mark.skipif(not _DSN, reason="WIKI_TEST_PG_DSN not set")

_ALEMBIC_INI = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api", "alembic.ini")
)
_ALEMBIC_DIR = os.path.dirname(_ALEMBIC_INI)


def _alembic_cfg(dsn: str) -> AlembicConfig:
    cfg = AlembicConfig(_ALEMBIC_INI)
    cfg.set_main_option("sqlalchemy.url", dsn)
    cfg.set_main_option("script_location", os.path.join(_ALEMBIC_DIR, "alembic"))
    return cfg


def _pg_indexes(conn: sa.Connection, table: str) -> list[str]:
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


def _teardown(engine: sa.Engine) -> None:
    """Drop all wiki tables so the round-trip starts from a clean slate.

    ``role_grants`` has no inbound FKs, so it is dropped first (mirrors
    ``test_rbac_migration.py``); the rest follow in dependency order.
    ``CASCADE`` makes the ordering defensive only.
    """
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS role_grants CASCADE"))
        for table in (
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
            "projects",
            "spaces",
            "organizations",
            "alembic_version",
        ):
            conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))


@_pg_only
def test_0018_hot_read_indexes_round_trip() -> None:
    """Postgres round-trip: build at 0017, upgrade to 0018, verify + downgrade."""
    assert _DSN, "WIKI_TEST_PG_DSN must be set (skip guard should have fired)"

    from k7e_api.config import get_settings

    _prev_db_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = _DSN
    get_settings.cache_clear()

    engine = sa.create_engine(_DSN, poolclass=sa.pool.NullPool)
    cfg = _alembic_cfg(_DSN)

    try:
        _teardown(engine)

        # 1. Build schema at 0017 (one step before 0018).
        alembic_command.upgrade(cfg, "0017_role_grants_and_viewer_seed")

        with engine.connect() as conn:
            for table, expected in _EXPECTED_INDEXES.items():
                built = set(_pg_indexes(conn, table))
                assert expected.isdisjoint(built), (
                    f"0018 indexes should not exist at 0017: {expected & built}"
                )

        # 2. Upgrade to 0018 — the migration under test.
        alembic_command.upgrade(cfg, "0018_hot_read_indexes")

        with engine.connect() as conn:
            for table, expected in _EXPECTED_INDEXES.items():
                built = set(_pg_indexes(conn, table))
                assert expected <= built, (
                    f"{table} missing 0018 indexes after upgrade: missing={expected - built}"
                )

        # 3. Downgrade one step back to 0017 — indexes must be dropped.
        alembic_command.downgrade(cfg, "0017_role_grants_and_viewer_seed")

        with engine.connect() as conn:
            for table, expected in _EXPECTED_INDEXES.items():
                built = set(_pg_indexes(conn, table))
                assert expected.isdisjoint(built), (
                    f"0018 indexes should be dropped after downgrade: {expected & built}"
                )

        # 4. Re-upgrade — idempotent rebuild after a clean downgrade.
        alembic_command.upgrade(cfg, "0018_hot_read_indexes")

        with engine.connect() as conn:
            for table, expected in _EXPECTED_INDEXES.items():
                built = set(_pg_indexes(conn, table))
                assert expected <= built, (
                    f"{table} missing 0018 indexes after re-upgrade: missing={expected - built}"
                )

        # 5. Cleanup — back to base.
        alembic_command.downgrade(cfg, "base")
    finally:
        if _prev_db_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = _prev_db_url
        get_settings.cache_clear()
        engine.dispose()
