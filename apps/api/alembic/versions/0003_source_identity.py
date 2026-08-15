"""source identity columns + source_page_links

Revision ID: 0003_source_identity
Revises: 0002_version_status_title
Create Date: 2026-06-15

Phase 2: tag raw documents with source identity/authority and add a
deterministic (source_system, source_external_id) -> knowledge_item mapping.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_source_identity"
down_revision = "0002_version_status_title"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "raw_documents",
        sa.Column(
            "source_system",
            sa.String(length=64),
            nullable=False,
            server_default="manual_upload",
        ),
    )
    op.add_column(
        "raw_documents",
        sa.Column("source_external_id", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "raw_documents",
        sa.Column("source_tier", sa.String(length=1), nullable=False, server_default="A"),
    )
    op.add_column(
        "raw_documents",
        sa.Column(
            "authority_weight",
            sa.Float(),
            nullable=False,
            server_default="1.0",
        ),
    )

    op.create_table(
        "source_page_links",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_system", sa.String(length=64), nullable=False),
        sa.Column("source_external_id", sa.String(length=512), nullable=False),
        sa.Column(
            "knowledge_item_id",
            sa.Uuid(),
            sa.ForeignKey("knowledge_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("source_system", "source_external_id", name="uq_source_page_link"),
    )
    # Index the FK so cascade-deletes from knowledge_items don't seq-scan.
    op.create_index(
        "ix_source_page_links_knowledge_item_id",
        "source_page_links",
        ["knowledge_item_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_source_page_links_knowledge_item_id",
        table_name="source_page_links",
    )
    op.drop_table("source_page_links")
    op.drop_column("raw_documents", "authority_weight")
    op.drop_column("raw_documents", "source_tier")
    op.drop_column("raw_documents", "source_external_id")
    op.drop_column("raw_documents", "source_system")
