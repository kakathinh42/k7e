"""add status and title to knowledge_item_versions

Revision ID: 0002_version_status_title
Revises: 0001_initial
Create Date: 2026-06-15

Phase 1 review-gate hardening: each version carries its own lifecycle status and
a title snapshot so the live KnowledgeItem only changes on publish/approve.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_version_status_title"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_item_versions",
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending_review",
        ),
    )
    op.add_column(
        "knowledge_item_versions",
        sa.Column("title", sa.Text(), nullable=True),
    )

    # Backfill: existing versions are historical -> 'superseded', except the
    # current (live) version of each item -> 'published'. ReviewTask.status, not
    # version.status, drives the pending queue, so this is safe for old rows.
    op.execute("UPDATE knowledge_item_versions SET status = 'superseded'")
    op.execute(
        "UPDATE knowledge_item_versions SET status = 'published' "
        "WHERE id IN (SELECT current_version_id FROM knowledge_items "
        "WHERE current_version_id IS NOT NULL)"
    )
    # Backfill title from the parent item.
    op.execute(
        "UPDATE knowledge_item_versions SET title = ("
        "SELECT title FROM knowledge_items "
        "WHERE knowledge_items.id = knowledge_item_versions.item_id)"
    )


def downgrade() -> None:
    op.drop_column("knowledge_item_versions", "title")
    op.drop_column("knowledge_item_versions", "status")
