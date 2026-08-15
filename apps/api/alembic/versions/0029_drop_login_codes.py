"""Drop login_codes.

The broker/handoff web-login flow (one-time codes) was removed in favour of
native email+password login + Personal Access Tokens. Reversible: downgrade
recreates the table exactly as 0026 defined it.

Revision ID: 0029_drop_login_codes
Revises: 0028_personal_access_tokens
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0029_drop_login_codes"
down_revision: str | None = "0028_personal_access_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_login_codes_org_id", table_name="login_codes")
    op.drop_index("ix_login_codes_code_hash", table_name="login_codes")
    op.drop_table("login_codes")


def downgrade() -> None:
    op.create_table(
        "login_codes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("email", sa.String(256), nullable=False),
        sa.Column("org_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_login_codes_code_hash", "login_codes", ["code_hash"], unique=True)
    op.create_index("ix_login_codes_org_id", "login_codes", ["org_id"])
