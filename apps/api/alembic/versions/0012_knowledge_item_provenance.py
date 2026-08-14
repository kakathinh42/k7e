"""Add provenance column to knowledge_items.

Revision ID: 0012_knowledge_item_provenance
Revises: 0011_knowledge_item_type
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0012_knowledge_item_provenance"
down_revision: str | None = "0011_knowledge_item_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_items",
        sa.Column("provenance", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("knowledge_items", "provenance")
