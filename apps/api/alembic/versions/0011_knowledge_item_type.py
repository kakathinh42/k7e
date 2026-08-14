"""Add type column to knowledge_items.

Revision ID: 0011_knowledge_item_type
Revises: 0010_raw_document_workflow_id
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0011_knowledge_item_type"
down_revision: str | None = "0010_raw_document_workflow_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_items",
        sa.Column(
            "type",
            sa.String(32),
            nullable=False,
            server_default="source",
        ),
    )


def downgrade() -> None:
    op.drop_column("knowledge_items", "type")
