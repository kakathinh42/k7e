"""Add workflow_id to raw_documents.

Revision ID: 0010_raw_document_workflow_id
Revises: 0009_wiki_links_target_idx
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0010_raw_document_workflow_id"
down_revision: str | None = "0009_wiki_links_target_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "raw_documents",
        sa.Column("workflow_id", sa.String(256), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("raw_documents", "workflow_id")
