"""Add allowed_groups to knowledge_items and raw_documents.

Revision ID: 0013_allowed_groups
Revises: 0012_knowledge_item_provenance
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0013_allowed_groups"
down_revision: str | None = "0012_knowledge_item_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("knowledge_items", sa.Column("allowed_groups", sa.JSON(), nullable=True))
    op.add_column("raw_documents", sa.Column("allowed_groups", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("raw_documents", "allowed_groups")
    op.drop_column("knowledge_items", "allowed_groups")
