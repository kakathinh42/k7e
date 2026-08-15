"""Add organizations, spaces, and projects tables (M1 multi-org tenant hierarchy).

Revision ID: 0015_org_space_project
Revises: 0014_pgvector_embeddings

Three new tables, purely additive — no changes to existing tables.

  Organization  (tenant root)
    └── Space   (knowledge domain within an org)
          └── Project  (finer-grained collection within a space)

Unique constraints
  - organizations.slug:       globally unique
  - spaces(org_id, slug):     unique per org
  - projects(space_id, slug): unique per space

Indexes on every FK column are created explicitly.
Downgrade drops the three tables in reverse dependency order.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0015_org_space_project"
down_revision: str | None = "0014_pgvector_embeddings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. organizations
    # ------------------------------------------------------------------
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
    )

    # ------------------------------------------------------------------
    # 2. spaces  (FK → organizations)
    # ------------------------------------------------------------------
    op.create_table(
        "spaces",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("org_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("default_language", sa.String(16), nullable=False, server_default="en"),
        sa.Column("okf_bundle_ref", sa.String(512), nullable=True),
        sa.Column("connector_config", sa.JSON(), nullable=True),
        sa.Column("review_policy", sa.JSON(), nullable=True),
        sa.UniqueConstraint("org_id", "slug", name="uq_space_org_slug"),
    )
    op.create_index("ix_spaces_org_id", "spaces", ["org_id"])

    # ------------------------------------------------------------------
    # 3. projects  (FK → spaces)
    # ------------------------------------------------------------------
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("space_id", sa.Uuid(), sa.ForeignKey("spaces.id"), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.UniqueConstraint("space_id", "slug", name="uq_project_space_slug"),
    )
    op.create_index("ix_projects_space_id", "projects", ["space_id"])


def downgrade() -> None:
    # Drop in reverse dependency order: projects → spaces → organizations
    op.drop_index("ix_projects_space_id", table_name="projects")
    op.drop_table("projects")

    op.drop_index("ix_spaces_org_id", table_name="spaces")
    op.drop_table("spaces")

    op.drop_table("organizations")
