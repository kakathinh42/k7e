"""personal_access_tokens: user-scoped PATs (PAT SSO Phase 1).

Revision ID: 0028_personal_access_tokens
Revises: 0027_users
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0028_personal_access_tokens"
down_revision: str | None = "0027_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "personal_access_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.String(320), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_personal_access_tokens_user_id",
        "personal_access_tokens",
        ["user_id"],
    )
    op.create_index(
        "ix_personal_access_tokens_token_hash",
        "personal_access_tokens",
        ["token_hash"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_personal_access_tokens_token_hash",
        table_name="personal_access_tokens",
    )
    op.drop_index(
        "ix_personal_access_tokens_user_id",
        table_name="personal_access_tokens",
    )
    op.drop_table("personal_access_tokens")
