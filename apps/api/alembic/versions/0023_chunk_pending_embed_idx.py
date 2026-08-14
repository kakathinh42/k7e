"""Partial index for the embedding-backfill poll (WHERE embedding IS NULL).

Supports the backfill's `WHERE embedding IS NULL ORDER BY created_at, id LIMIT N`
query. Built CONCURRENTLY so it does not lock wiki_chunks.

Revision ID: 0023_chunk_pending_embed_idx
Revises: 0022_chunk_embed_nullable
"""

from __future__ import annotations

from alembic import op

revision: str = "0023_chunk_pending_embed_idx"
down_revision: str | None = "0022_chunk_embed_nullable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_wiki_chunks_pending_embedding "
            "ON wiki_chunks (created_at, id) WHERE embedding IS NULL"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_wiki_chunks_pending_embedding")
