"""knowledge_items.domain + item_tags table (M4 classification).

Revision ID: 0020_classification
Revises: 0019_teams_membership

Purely additive: a nullable ``domain`` column (indexed) on ``knowledge_items``
and a new normalized ``item_tags`` join table. No existing row changes; no
access path is affected (classification is orthogonal to permissions).

SQLite tests skip migrations (``Base.metadata.create_all``); this migration is
exercised on Postgres by ``tests/api/test_classification_migration.py`` (gated
on ``WIKI_TEST_PG_DSN``).

Lock note (cf. 0018): ``add_column`` + plain ``CREATE INDEX`` on the existing
``knowledge_items`` table take a brief SHARE lock. Negligible at current scale
(``knowledge_items`` is small); if that table grows large before a production
deploy, switch ``ix_knowledge_items_domain`` to ``CREATE INDEX CONCURRENTLY`` in
a non-transactional migration to avoid blocking writes.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0020_classification"
down_revision: str | None = "0019_teams_membership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("knowledge_items", sa.Column("domain", sa.String(32), nullable=True))
    op.create_index("ix_knowledge_items_domain", "knowledge_items", ["domain"])
    op.create_table(
        "item_tags",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("org_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column(
            "item_id",
            sa.Uuid(),
            sa.ForeignKey("knowledge_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tag", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("item_id", "tag", name="uq_item_tag"),
    )
    op.create_index("ix_item_tags_org_id", "item_tags", ["org_id"])
    op.create_index("ix_item_tags_item_id", "item_tags", ["item_id"])
    op.create_index("ix_item_tags_tag", "item_tags", ["tag"])


def downgrade() -> None:
    op.drop_index("ix_item_tags_tag", table_name="item_tags")
    op.drop_index("ix_item_tags_item_id", table_name="item_tags")
    op.drop_index("ix_item_tags_org_id", table_name="item_tags")
    op.drop_table("item_tags")
    op.drop_index("ix_knowledge_items_domain", table_name="knowledge_items")
    op.drop_column("knowledge_items", "domain")
