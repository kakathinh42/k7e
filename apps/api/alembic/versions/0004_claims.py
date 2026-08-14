"""claims table

Revision ID: 0004_claims
Revises: 0003_source_identity
Create Date: 2026-06-15

Phase 3: attributed claims mined from conversational (Tier-B) sources.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_claims"
down_revision = "0003_source_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "claims",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "raw_document_id",
            sa.Uuid(),
            sa.ForeignKey("raw_documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "linked_item_id",
            sa.Uuid(),
            sa.ForeignKey("knowledge_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("subject", sa.String(length=512), nullable=True),
        sa.Column("speaker", sa.String(length=255), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending_review",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_claims_linked_item_id", "claims", ["linked_item_id"])
    op.create_index("ix_claims_status", "claims", ["status"])


def downgrade() -> None:
    op.drop_index("ix_claims_status", table_name="claims")
    op.drop_index("ix_claims_linked_item_id", table_name="claims")
    op.drop_table("claims")
