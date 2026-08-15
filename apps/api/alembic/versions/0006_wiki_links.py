"""wiki_links table for the page<->page graph.

Revision ID: 0006_wiki_links
Revises: 0005_wiki_chunks
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0006_wiki_links"
down_revision: str | None = "0005_wiki_chunks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wiki_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_item_id", sa.Uuid(), nullable=False),
        sa.Column("target_item_id", sa.Uuid(), nullable=False),
        sa.Column("relation", sa.String(32), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("origin", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_item_id"], ["knowledge_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_item_id"], ["knowledge_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_item_id",
            "target_item_id",
            "relation",
            "origin",
            name="uq_wiki_link",
        ),
    )
    op.create_index("ix_wiki_links_source_item_id", "wiki_links", ["source_item_id"])


def downgrade() -> None:
    op.drop_index("ix_wiki_links_source_item_id", table_name="wiki_links")
    op.drop_table("wiki_links")
