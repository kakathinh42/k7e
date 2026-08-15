"""wiki_chunks.embedding nullable

Lets the mirror persist chunk text before a vector exists; the scheduled
embedding backfill fills embeddings asynchronously. Downgrade re-adds NOT NULL
and will FAIL if any NULL embeddings remain (expected — backfill first).

Revision ID: 0022_chunk_embed_nullable
Revises: 0021_client_apps
"""

from __future__ import annotations

from alembic import op

revision: str = "0022_chunk_embed_nullable"
down_revision: str | None = "0021_client_apps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("wiki_chunks", "embedding", nullable=True)


def downgrade() -> None:
    op.alter_column("wiki_chunks", "embedding", nullable=False)
