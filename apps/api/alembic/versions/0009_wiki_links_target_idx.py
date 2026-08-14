"""Add ix_wiki_links_target_item_id index.

Revision ID: 0009_wiki_links_target_idx
Revises: 0008_ingest_runs
"""

from alembic import op

revision: str = "0009_wiki_links_target_idx"
down_revision: str | None = "0008_ingest_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_wiki_links_target_item_id", "wiki_links", ["target_item_id"])


def downgrade() -> None:
    op.drop_index("ix_wiki_links_target_item_id", table_name="wiki_links")
