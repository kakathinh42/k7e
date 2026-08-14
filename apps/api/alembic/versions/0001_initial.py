"""Initial schema – all MVP tables.

Creates all six MVP tables (sources, raw_documents, knowledge_items,
knowledge_item_versions, gate_decisions, review_tasks), enables the
pg_trgm extension, and adds indexes required for search and deduplication.

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-11
"""

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------
revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Extensions
    # ------------------------------------------------------------------
    # pg_trgm enables trigram similarity indexes used for title / body search.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # ------------------------------------------------------------------
    # sources
    # ------------------------------------------------------------------
    op.create_table(
        "sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("extra_metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ------------------------------------------------------------------
    # raw_documents
    # ------------------------------------------------------------------
    op.create_table(
        "raw_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("object_store_ref", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("extra_metadata", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ------------------------------------------------------------------
    # knowledge_items  (created WITHOUT the circular FK first)
    # ------------------------------------------------------------------
    op.create_table(
        "knowledge_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(512), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        # current_version_id FK added below after knowledge_item_versions exists
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_knowledge_items_slug"),
    )

    # ------------------------------------------------------------------
    # knowledge_item_versions  (depends on knowledge_items + raw_documents)
    # ------------------------------------------------------------------
    op.create_table(
        "knowledge_item_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("raw_document_id", sa.Uuid(), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("markdown_body", sa.Text(), nullable=False),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=True),
        sa.Column("extra_metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["knowledge_items.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["raw_document_id"],
            ["raw_documents.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ------------------------------------------------------------------
    # Resolve circular FK: knowledge_items.current_version_id
    # ------------------------------------------------------------------
    op.create_foreign_key(
        "fk_ki_current_version_id",
        "knowledge_items",
        "knowledge_item_versions",
        ["current_version_id"],
        ["id"],
    )

    # ------------------------------------------------------------------
    # gate_decisions
    # ------------------------------------------------------------------
    op.create_table(
        "gate_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("has_redaction", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["knowledge_item_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ------------------------------------------------------------------
    # review_tasks
    # ------------------------------------------------------------------
    op.create_table(
        "review_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("assigned_to", sa.String(255), nullable=True),
        sa.Column("decided_by", sa.String(255), nullable=True),
        sa.Column("decision_comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["knowledge_item_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ------------------------------------------------------------------
    # Indexes
    # ------------------------------------------------------------------

    # knowledge_items.slug – fast slug lookups (unique constraint already
    # provides a unique B-tree index; adding a named regular index for
    # explicit, discoverable, non-unique lookup patterns).
    op.create_index(
        "ix_knowledge_items_slug",
        "knowledge_items",
        ["slug"],
    )

    # raw_documents.sha256 – deduplication check on ingest
    op.create_index(
        "ix_raw_documents_sha256",
        "raw_documents",
        ["sha256"],
    )

    # knowledge_items.title – GIN trigram index for fuzzy search
    op.create_index(
        "ix_knowledge_items_title_trgm",
        "knowledge_items",
        ["title"],
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )

    # knowledge_item_versions.markdown_body – GIN trigram index for body search
    op.create_index(
        "ix_kiv_markdown_body_trgm",
        "knowledge_item_versions",
        ["markdown_body"],
        postgresql_using="gin",
        postgresql_ops={"markdown_body": "gin_trgm_ops"},
    )


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    # Drop indexes first (reverse order of creation)
    op.drop_index("ix_kiv_markdown_body_trgm", table_name="knowledge_item_versions")
    op.drop_index("ix_knowledge_items_title_trgm", table_name="knowledge_items")
    op.drop_index("ix_raw_documents_sha256", table_name="raw_documents")
    op.drop_index("ix_knowledge_items_slug", table_name="knowledge_items")

    # Drop tables (leaf → root to satisfy FK order)
    op.drop_table("review_tasks")
    op.drop_table("gate_decisions")

    # Remove circular FK before dropping knowledge_item_versions
    op.drop_constraint(
        "fk_ki_current_version_id",
        "knowledge_items",
        type_="foreignkey",
    )

    op.drop_table("knowledge_item_versions")
    op.drop_table("knowledge_items")
    op.drop_table("raw_documents")
    op.drop_table("sources")

    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
