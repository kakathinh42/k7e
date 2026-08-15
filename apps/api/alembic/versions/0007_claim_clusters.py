"""claim_clusters table + claims.cluster_id

Revision ID: 0007_claim_clusters
Revises: 0006_wiki_links
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0007_claim_clusters"
down_revision: str | None = "0006_wiki_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "claim_clusters",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("canonical_text", sa.Text(), nullable=False),
        sa.Column("subject", sa.String(512), nullable=True),
        sa.Column("centroid", sa.JSON(), nullable=False),
        sa.Column("support_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("folded_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["folded_version_id"],
            ["knowledge_item_versions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("claims", sa.Column("cluster_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_claims_cluster_id",
        "claims",
        "claim_clusters",
        ["cluster_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_claims_cluster_id", "claims", ["cluster_id"])


def downgrade() -> None:
    op.drop_index("ix_claims_cluster_id", table_name="claims")
    op.drop_constraint("fk_claims_cluster_id", "claims", type_="foreignkey")
    op.drop_column("claims", "cluster_id")
    op.drop_table("claim_clusters")
