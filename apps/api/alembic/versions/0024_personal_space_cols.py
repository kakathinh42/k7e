"""personal space columns: spaces.owner_user_id, raw_documents.space_id/created_by.

Revision ID: 0024_personal_space_cols
Revises: 0023_chunk_pending_embed_idx

Adds the schema seam for personal spaces (private per-user knowledge):

  - ``spaces.owner_user_id`` (nullable) — set ⇒ this Space is one user's
    private space (JIT-provisioned). ``uq_space_org_owner`` is a *partial*
    unique index on ``(org_id, owner_user_id) WHERE owner_user_id IS NOT
    NULL`` — at most one personal space per user per org, while NULL rows
    (ordinary, non-personal spaces) never collide.
  - ``raw_documents.space_id`` (nullable FK -> spaces.id) — target space for
    space-routed ingestion; NULL keeps today's legacy default-bundle routing.
  - ``raw_documents.created_by`` (nullable) — uploader identity (JWT sub /
    X-User-Id header), used for provenance and to enforce the personal
    ingest daily cap.

Purely additive: all three new columns are nullable, so no existing row
needs a value and no backfill is required.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0024_personal_space_cols"
down_revision: str | None = "0023_chunk_pending_embed_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("spaces", sa.Column("owner_user_id", sa.String(256), nullable=True))
    op.create_index(
        "uq_space_org_owner",
        "spaces",
        ["org_id", "owner_user_id"],
        unique=True,
        postgresql_where=sa.text("owner_user_id IS NOT NULL"),
        sqlite_where=sa.text("owner_user_id IS NOT NULL"),
    )
    op.add_column(
        "raw_documents",
        sa.Column("space_id", sa.Uuid(), sa.ForeignKey("spaces.id"), nullable=True),
    )
    op.create_index("ix_raw_documents_space_id", "raw_documents", ["space_id"])
    op.add_column("raw_documents", sa.Column("created_by", sa.String(256), nullable=True))


def downgrade() -> None:
    op.drop_column("raw_documents", "created_by")
    op.drop_index("ix_raw_documents_space_id", table_name="raw_documents")
    op.drop_column("raw_documents", "space_id")
    op.drop_index("uq_space_org_owner", table_name="spaces")
    op.drop_column("spaces", "owner_user_id")
