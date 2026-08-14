"""wiki_chunks table for embeddings.

Revision ID: 0005_wiki_chunks
Revises: 0004_claims
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0005_wiki_chunks"
down_revision: str | None = "0004_claims"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wiki_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["knowledge_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["version_id"], ["knowledge_item_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_wiki_chunks_version_id", "wiki_chunks", ["version_id"])


def downgrade() -> None:
    op.drop_index("ix_wiki_chunks_version_id", table_name="wiki_chunks")
    op.drop_table("wiki_chunks")
