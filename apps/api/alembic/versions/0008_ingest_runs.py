"""ingest_runs table — per-upload token usage + estimated $ cost.

Revision ID: 0008_ingest_runs
Revises: 0007_claim_clusters
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0008_ingest_runs"
down_revision: str | None = "0007_claim_clusters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ingest_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("raw_document_id", sa.Uuid(), nullable=True),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("source_slug", sa.String(255), nullable=True),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("llm_calls", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["raw_document_id"], ["raw_documents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ingest_runs_raw_document_id", "ingest_runs", ["raw_document_id"])
    op.create_index("ix_ingest_runs_created_at", "ingest_runs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_ingest_runs_created_at", table_name="ingest_runs")
    op.drop_index("ix_ingest_runs_raw_document_id", table_name="ingest_runs")
    op.drop_table("ingest_runs")
