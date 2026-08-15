"""Index hot read/search columns: status, current_version_id, item_id.

Revision ID: 0018_hot_read_indexes
Revises: 0017_role_grants_and_viewer_seed

Adds the three single-column btree indexes the read/search path filters or
joins on every request but which were never indexed:

  * ``knowledge_items.status``           — every read/search filters
    ``status == 'published'`` (a full scan without this index).
  * ``knowledge_items.current_version_id`` — every read joins the current
    version row via this self-referential FK. ``use_alter=True`` defers the
    *FK constraint* to an ``ALTER TABLE`` (emitted by Alembic at create time);
    the *index* is orthogonal and is created directly here.
  * ``wiki_chunks.item_id``              — used by the lint related-page
    lookup (``WHERE item_id IN (...)``), the mirror's chunk delete/select by
    item, and the ``ondelete="CASCADE"`` FK Postgres services via this index.
    (The vector-search chunk load filters on ``version_id`` — already indexed
    by ``0005`` — not ``item_id``.)

Purely additive DDL — no column is added, dropped, or retyped, and no existing
row is touched. Downgrade drops exactly these three indexes.

Notes:
  - ``CREATE INDEX`` acquires a SHARE lock during the build. For zero-downtime
    deployments consider creating these with ``CONCURRENTLY`` in a separate,
    non-transactional migration.
  - SQLite tests skip migrations entirely (``Base.metadata.create_all``), so
    the declarative ``index=True`` already builds these indexes there; this
    migration is exercised on Postgres by the round-trip test
    (``test_m0_indexes.py``) when ``WIKI_TEST_PG_DSN`` is set.
"""

from alembic import op

revision: str = "0018_hot_read_indexes"
down_revision: str | None = "0017_role_grants_and_viewer_seed"
branch_labels = None
depends_on = None


# (index_name, table, column) for each hot-read index, in creation order.
_INDEXES: list[tuple[str, str, str]] = [
    ("ix_knowledge_items_status", "knowledge_items", "status"),
    ("ix_knowledge_items_current_version_id", "knowledge_items", "current_version_id"),
    ("ix_wiki_chunks_item_id", "wiki_chunks", "item_id"),
]


def upgrade() -> None:
    for index_name, table, column in _INDEXES:
        op.create_index(index_name, table, [column])


def downgrade() -> None:
    # Reverse of upgrade: drop in reverse creation order.
    for index_name, table, _column in reversed(_INDEXES):
        op.drop_index(index_name, table_name=table)
