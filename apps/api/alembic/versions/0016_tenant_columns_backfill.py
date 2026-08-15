"""Add org_id / space_id / project_id to tenant-scoped tables + backfill.

Revision ID: 0016_tenant_columns_backfill
Revises: 0015_org_space_project

Every table that holds tenant-owned content gains ``org_id`` (FK →
organizations).  ``knowledge_items`` additionally gains ``space_id`` (FK →
spaces, NOT NULL after backfill) and ``project_id`` (FK → projects, stays
nullable — items may not belong to a specific project).

Safe sequence — nullable → backfill → NOT NULL:
  1. Add columns as nullable (no data loss risk; existing rows stay valid).
  2. Seed a deterministic ``default`` org + ``engineering`` space so the
     backfill has a stable target.  Deterministic UUIDs make re-runs
     idempotent (ON CONFLICT DO NOTHING on each respective unique key).
  3. UPDATE all pre-existing rows to point at the seeded org/space.
  4. ALTER COLUMN … SET NOT NULL for org_id and space_id (project_id stays
     nullable).
  5. Create FK constraints and indexes.

Downgrade:
  - Drop FK constraints and indexes in reverse order.
  - Drop the added columns (data-loss on columns is acceptable per the plan —
    this only drops the FK pointers, not the org/space rows themselves).
  - Delete the seeded space and org (they were injected by this migration).

Notes:
  - The ORM keeps the new columns nullable=True so SQLite tests (create_all)
    still work without needing to enforce NOT NULL.  The NOT NULL constraint
    is applied at the DB level by this migration after backfill.
  - SET NOT NULL (step 4) acquires ACCESS EXCLUSIVE on each table and performs
    a full-table NULL scan; acceptable for maintenance deployments on small
    tables.  For large production tables, replace with CHECK NOT VALID +
    VALIDATE CONSTRAINT + SET NOT NULL to avoid long lock windows.
  - CREATE INDEX (step 7) acquires a SHARE lock during the build.  For zero-
    downtime deployments consider creating indexes with CONCURRENTLY in a
    separate, non-transactional migration.
  - The backfill UPDATEs use ``WHERE org_id IS NULL`` so re-running upgrade
    after a failed partial run is safe.
  - op.get_bind() is deprecated in Alembic 1.9+.  Kept here for consistency
    with migration 0014 (codebase-wide pattern).
"""

import uuid

import sqlalchemy as sa
from alembic import op

revision: str = "0016_tenant_columns_backfill"
down_revision: str | None = "0015_org_space_project"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# Deterministic seed UUIDs — must match the test assertions exactly
# ---------------------------------------------------------------------------

_ORG_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
_SPACE_ID = uuid.UUID("00000000-0000-0000-0000-0000000000b1")

# ---------------------------------------------------------------------------
# Tables that gain org_id (all tenant-scoped content tables)
# ---------------------------------------------------------------------------

_ORG_ID_TABLES = [
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
]


def upgrade() -> None:
    bind = op.get_bind()  # op.get_bind() deprecated in Alembic 1.9+; kept for codebase consistency

    # -----------------------------------------------------------------------
    # 1. Add nullable org_id column to every tenant-scoped table
    # -----------------------------------------------------------------------
    for table in _ORG_ID_TABLES:
        op.add_column(table, sa.Column("org_id", sa.Uuid(), nullable=True))

    # -----------------------------------------------------------------------
    # 2. Add nullable space_id and project_id to knowledge_items
    # -----------------------------------------------------------------------
    op.add_column("knowledge_items", sa.Column("space_id", sa.Uuid(), nullable=True))
    op.add_column("knowledge_items", sa.Column("project_id", sa.Uuid(), nullable=True))

    # -----------------------------------------------------------------------
    # 3. Seed default org + space (idempotent via ON CONFLICT DO NOTHING)
    #
    # Organizations: conflict on PK (id) — globally unique.
    # Spaces: conflict on the (org_id, slug) unique constraint so a re-run
    # is safe even if the same space exists under this org with a *different*
    # id (e.g., from a prior partial migration).
    # -----------------------------------------------------------------------
    bind.execute(
        sa.text(
            "INSERT INTO organizations (id, slug, name, created_at) "
            "VALUES (:i, 'default', 'Default', now()) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"i": _ORG_ID},
    )
    bind.execute(
        sa.text(
            "INSERT INTO spaces (id, org_id, slug, name, default_language) "
            "VALUES (:s, :o, 'engineering', 'Engineering', 'en') "
            "ON CONFLICT ON CONSTRAINT uq_space_org_slug DO NOTHING"
        ),
        {"s": _SPACE_ID, "o": _ORG_ID},
    )

    # -----------------------------------------------------------------------
    # 4. Backfill all pre-existing rows to the seeded org/space
    #
    # source_page_links.org_id is derived via JOIN on knowledge_items so it
    # stays consistent with the item it links to, even if backfill order
    # were to change in a future migration.
    # -----------------------------------------------------------------------
    for table in _ORG_ID_TABLES:
        if table == "source_page_links":
            # Derive org from the linked knowledge_item for correctness
            bind.execute(
                sa.text(
                    "UPDATE source_page_links spl "
                    "SET org_id = ki.org_id "
                    "FROM knowledge_items ki "
                    "WHERE spl.knowledge_item_id = ki.id "
                    "AND spl.org_id IS NULL"
                )
            )
        else:
            bind.execute(
                sa.text(
                    f"UPDATE {table} SET org_id = :o WHERE org_id IS NULL"  # noqa: S608
                ),
                {"o": _ORG_ID},
            )

    bind.execute(
        sa.text("UPDATE knowledge_items SET space_id = :s WHERE space_id IS NULL"),
        {"s": _SPACE_ID},
    )
    # project_id intentionally left NULL — items don't necessarily belong to a project

    # -----------------------------------------------------------------------
    # 5. Enforce NOT NULL on org_id for all tables (after backfill)
    #    Acquires ACCESS EXCLUSIVE + full-table NULL scan per table.
    #    Acceptable for maintenance windows; see module docstring for the
    #    zero-downtime alternative.
    # -----------------------------------------------------------------------
    for table in _ORG_ID_TABLES:
        op.alter_column(table, "org_id", nullable=False)

    # Enforce NOT NULL on space_id for knowledge_items (project_id stays nullable)
    op.alter_column("knowledge_items", "space_id", nullable=False)

    # -----------------------------------------------------------------------
    # 6. Create FK constraints
    # -----------------------------------------------------------------------
    for table in _ORG_ID_TABLES:
        op.create_foreign_key(
            f"fk_{table}_org_id",
            table,
            "organizations",
            ["org_id"],
            ["id"],
        )

    op.create_foreign_key(
        "fk_knowledge_items_space_id",
        "knowledge_items",
        "spaces",
        ["space_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_knowledge_items_project_id",
        "knowledge_items",
        "projects",
        ["project_id"],
        ["id"],
    )

    # -----------------------------------------------------------------------
    # 7. Create indexes on the new FK columns
    #    Acquires SHARE lock during each build.  For zero-downtime deployments
    #    consider a separate migration using CREATE INDEX CONCURRENTLY.
    # -----------------------------------------------------------------------
    for table in _ORG_ID_TABLES:
        op.create_index(f"ix_{table}_org_id", table, ["org_id"])

    op.create_index("ix_knowledge_items_space_id", "knowledge_items", ["space_id"])
    op.create_index("ix_knowledge_items_project_id", "knowledge_items", ["project_id"])


def downgrade() -> None:
    # -----------------------------------------------------------------------
    # 1. Drop indexes (reverse of upgrade step 7)
    # -----------------------------------------------------------------------
    op.drop_index("ix_knowledge_items_project_id", table_name="knowledge_items")
    op.drop_index("ix_knowledge_items_space_id", table_name="knowledge_items")

    for table in reversed(_ORG_ID_TABLES):
        op.drop_index(f"ix_{table}_org_id", table_name=table)

    # -----------------------------------------------------------------------
    # 2. Drop FK constraints (reverse of upgrade step 6)
    # -----------------------------------------------------------------------
    op.drop_constraint("fk_knowledge_items_project_id", "knowledge_items", type_="foreignkey")
    op.drop_constraint("fk_knowledge_items_space_id", "knowledge_items", type_="foreignkey")

    for table in reversed(_ORG_ID_TABLES):
        op.drop_constraint(f"fk_{table}_org_id", table, type_="foreignkey")

    # -----------------------------------------------------------------------
    # 3. Drop columns (reverse of upgrade steps 1–2)
    # -----------------------------------------------------------------------
    op.drop_column("knowledge_items", "project_id")
    op.drop_column("knowledge_items", "space_id")

    for table in reversed(_ORG_ID_TABLES):
        op.drop_column(table, "org_id")

    # -----------------------------------------------------------------------
    # 4. Remove seeded org + space (they were created by this migration)
    #    Delete space first (FK → organizations), then org.
    # -----------------------------------------------------------------------
    bind = op.get_bind()  # op.get_bind() deprecated in Alembic 1.9+; kept for codebase consistency
    bind.execute(
        sa.text("DELETE FROM spaces WHERE id = :s"),
        {"s": _SPACE_ID},
    )
    bind.execute(
        sa.text("DELETE FROM organizations WHERE id = :o"),
        {"o": _ORG_ID},
    )
