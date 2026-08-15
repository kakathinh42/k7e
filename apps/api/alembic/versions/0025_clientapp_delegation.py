"""clientapp delegation: can_delegate_identity + allowed_identity_domain.

Revision ID: 0025_clientapp_delegation
Revises: 0024_personal_space_cols

Adds the delegated-identity (trusted subsystem) seam to ``client_apps``:

  - ``can_delegate_identity`` (NOT NULL, server default false) — when true,
    this app may act on behalf of an end user via ``X-On-Behalf-Of-Email``.
    Off by default; only explicitly-trusted apps (e.g. chat-agent) get it.
  - ``allowed_identity_domain`` (nullable) — optional guard restricting which
    email domain this app may assert (e.g. "example.com"); NULL = no restriction.

Purely additive: the boolean carries a server default so existing rows need no
backfill, and the domain column is nullable.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0025_clientapp_delegation"
down_revision: str | None = "0024_personal_space_cols"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "client_apps",
        sa.Column(
            "can_delegate_identity",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "client_apps",
        sa.Column("allowed_identity_domain", sa.String(256), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("client_apps", "allowed_identity_domain")
    op.drop_column("client_apps", "can_delegate_identity")
