"""client_apps table (M6 consumer app identity).

Revision ID: 0021_client_apps
Revises: 0020_classification

Purely additive: a new ``client_apps`` registry table for first-class app
principals. No existing row changes.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0021_client_apps"
down_revision: str | None = "0020_classification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_apps",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("org_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("api_key_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("org_id", "slug", name="uq_client_app_org_slug"),
    )
    op.create_index("ix_client_apps_org_id", "client_apps", ["org_id"])
    op.create_index("ix_client_apps_api_key_hash", "client_apps", ["api_key_hash"])


def downgrade() -> None:
    op.drop_index("ix_client_apps_api_key_hash", table_name="client_apps")
    op.drop_index("ix_client_apps_org_id", table_name="client_apps")
    op.drop_table("client_apps")
