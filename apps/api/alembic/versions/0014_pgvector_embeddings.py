"""Convert wiki_chunks.embedding from JSON to pgvector + HNSW index.

Revision ID: 0014_pgvector_embeddings
Revises: 0013_allowed_groups

PostgreSQL only. Requires the pgvector extension (preinstalled in the
``pgvector/pgvector:pg16`` image). Existing embeddings must already be the
configured dimension (text-embedding-3-small -> 1536); the cast below assumes
each JSON array has exactly EMBEDDING_DIM elements.

Downgrade note: the vector->json reverse cast is lossy — pgvector stores
coordinates as float32, so the original float64 JSON values are not
recoverable. This is acceptable for cosine-similarity workloads.
"""

from alembic import op

revision: str = "0014_pgvector_embeddings"
down_revision: str | None = "0013_allowed_groups"
branch_labels = None
depends_on = None

_INDEX = "ix_wiki_chunks_embedding_hnsw"
_EMBEDDING_DIM = (
    1536  # text-embedding-3-small; pinned at generation time (do not import the live constant)
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # No-op on SQLite/others; the JSON column already works there.
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # JSON array text (e.g. "[0.1, 0.2]") is valid pgvector input.
    op.execute(
        f"ALTER TABLE wiki_chunks "
        f"ALTER COLUMN embedding TYPE vector({_EMBEDDING_DIM}) "
        f"USING embedding::text::vector"
    )
    op.execute(f"CREATE INDEX {_INDEX} ON wiki_chunks USING hnsw (embedding vector_cosine_ops)")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
    op.execute(
        "ALTER TABLE wiki_chunks ALTER COLUMN embedding TYPE json USING embedding::text::json"
    )
    # Extension is intentionally left installed (other objects may use it).
