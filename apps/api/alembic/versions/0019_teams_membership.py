"""teams + memberships tables + spaces.visibility (M3 Step A).

Revision ID: 0019_teams_membership
Revises: 0018_hot_read_indexes

Adds the two tables backing M3 Team & Membership, plus the advisory
``spaces.visibility`` column (default ``'members'``). Purely additive except
for the new column on ``spaces`` — no existing row's access changes: the
seeded ``group:public viewer @ org:default`` grant from 0017 still admits
readers, and ``visibility`` is a label (the RBAC resolver consults grants,
not this column).

Backfill decision: existing spaces (e.g. ``default``-org spaces) are set to
``visibility='members'`` via the column's ``server_default`` at ADD COLUMN
time (Postgres populates existing rows with the default in the same
statement). ``'members'`` is chosen over ``'org'`` for simplicity: the column
is advisory and not yet read by any access path, so the label is a
forward-looking hint that team-created spaces are members-only. Existing
spaces keep their current (grant-governed) read behavior regardless of the
label.

Safe sequence:
  1. ``create_table('teams', ...)`` + ``ix_teams_org_id`` + ``uq_team_org_slug``
     + ``uq_team_space`` (one team per space).
  2. ``create_table('memberships', ...)`` + ``ix_memberships_team_id`` +
     ``ix_memberships_user_id`` + ``uq_membership_team_user``.
  3. ``add_column('spaces', visibility NOT NULL DEFAULT 'members')`` — Postgres
     backfills existing rows to ``'members'`` in the same statement.

Downgrade reverses all three in reverse order: drop the column, then drop
``memberships`` and ``teams``.

Notes:
  - SQLite tests skip migrations (``Base.metadata.create_all``); this migration
    is exercised on Postgres by ``tests/api/test_team_migration.py`` when
    ``WIKI_TEST_PG_DSN`` is set.
  - ``teams.space_id`` is ``UNIQUE`` (one team per space).
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0019_teams_membership"
down_revision: str | None = "0018_hot_read_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. teams
    op.create_table(
        "teams",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("org_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("space_id", sa.Uuid(), sa.ForeignKey("spaces.id"), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("created_by", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("org_id", "slug", name="uq_team_org_slug"),
        sa.UniqueConstraint("space_id", name="uq_team_space"),
    )
    op.create_index("ix_teams_org_id", "teams", ["org_id"])

    # 2. memberships
    op.create_table(
        "memberships",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "team_id",
            sa.Uuid(),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(256), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("team_id", "user_id", name="uq_membership_team_user"),
    )
    op.create_index("ix_memberships_team_id", "memberships", ["team_id"])
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])

    # 3. spaces.visibility — server_default backfills existing rows to 'members'.
    op.add_column(
        "spaces",
        sa.Column(
            "visibility",
            sa.String(16),
            nullable=False,
            server_default="members",
        ),
    )


def downgrade() -> None:
    op.drop_column("spaces", "visibility")
    op.drop_index("ix_memberships_user_id", table_name="memberships")
    op.drop_index("ix_memberships_team_id", table_name="memberships")
    op.drop_table("memberships")
    op.drop_index("ix_teams_org_id", table_name="teams")
    op.drop_table("teams")
