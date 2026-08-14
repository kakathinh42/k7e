"""role_grants table + all-org viewer seed

Revision ID: 0017_role_grants_and_viewer_seed
Revises: 0016_tenant_columns_backfill

Adds the ``role_grants`` table backing M2 hierarchical RBAC, then seeds the
single behavior-preserving grant: every authenticated caller is implicitly in
the ``public`` group (Piece 1), so a ``group:public`` ``viewer`` grant on the
``default`` org reproduces today's "everyone reads all public content" exactly.
That one row is the whole cutover — no caller's read access changes until real
grants are added.

``role_grants`` is deliberately NOT an ``org_id``-scoped content table: a
grant's tenant is implied by its ``(scope_kind, scope_id)`` ref (FK-less
polymorphic — discriminated by ``scope_kind``, referential integrity enforced
in application code). It therefore gets no ``org_id`` column and is not routed
through ``scoped()``.

Safe sequence:
  1. Create ``role_grants`` (columns + ``uq_role_grant`` + both indexes) —
     purely additive, no existing table touched.
  2. Seed the all-org ``group:public`` ``viewer`` grant. Idempotent via
     ``ON CONFLICT (principal_kind, principal_id, role, scope_kind, scope_id)
     DO NOTHING`` so re-runs after a partial failure are safe.

Downgrade reverses both: delete the seeded grant, drop indexes + constraint +
table.

Notes:
  - The seed targets ``0016``'s deterministic ``default`` org id
    (``_ORG_ID``). The grant itself gets its own deterministic seed id
    (``_GRANT_ID``) for traceability, but idempotency keys on the unique
    constraint (not the PK) so a re-run is a no-op even if a row with the same
    5-tuple but a different id already exists.
  - ``op.get_bind()`` is deprecated in Alembic 1.9+; kept here for consistency
    with migration 0016 (codebase-wide pattern).
  - ``CREATE INDEX`` (step 1) acquires a SHARE lock during the build. For
    zero-downtime deployments consider creating indexes with ``CONCURRENTLY``
    in a separate, non-transactional migration.
  - The seed's ``ON CONFLICT ... DO NOTHING`` is Postgres syntax; SQLite tests
    skip migrations entirely (``Base.metadata.create_all``), so it is only
    exercised by the Postgres round-trip test (``test_rbac_migration.py``).
"""

import uuid

import sqlalchemy as sa
from alembic import op

revision: str = "0017_role_grants_and_viewer_seed"
down_revision: str | None = "0016_tenant_columns_backfill"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# Deterministic seed UUIDs — must match the test assertions exactly.
# _ORG_ID is 0016's seeded ``default`` org (the all-org target of the grant).
# ---------------------------------------------------------------------------

_ORG_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")  # from 0016
_GRANT_ID = uuid.UUID("00000000-0000-0000-0000-0000000000c1")  # deterministic seed id


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Create role_grants (columns + uq_role_grant + both indexes)
    #    Purely additive — no existing table is touched.
    # ------------------------------------------------------------------
    op.create_table(
        "role_grants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("principal_kind", sa.String(16), nullable=False),
        sa.Column("principal_id", sa.String(512), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("scope_kind", sa.String(16), nullable=False),
        sa.Column("scope_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "principal_kind",
            "principal_id",
            "role",
            "scope_kind",
            "scope_id",
            name="uq_role_grant",
        ),
    )
    op.create_index("ix_role_grant_principal", "role_grants", ["principal_kind", "principal_id"])
    op.create_index("ix_role_grant_scope", "role_grants", ["scope_kind", "scope_id"])

    # ------------------------------------------------------------------
    # 2. Seed the behavior-preserving all-org viewer grant.
    #    Every authenticated caller is implicitly in the `public` group
    #    (Piece 1), so this grant makes every caller a viewer on the default
    #    org = today's read behavior. Idempotent via ON CONFLICT DO NOTHING on
    #    the unique constraint (not the PK) so a re-run is a no-op even if a
    #    row with the same 5-tuple but a different id already exists.
    # ------------------------------------------------------------------
    bind = op.get_bind()  # deprecated in Alembic 1.9+; kept for codebase consistency
    bind.execute(
        sa.text(
            "INSERT INTO role_grants "
            "(id, principal_kind, principal_id, role, scope_kind, scope_id, created_at) "
            "VALUES (:id, 'group', 'public', 'viewer', 'org', :org_id, now()) "
            "ON CONFLICT (principal_kind, principal_id, role, scope_kind, scope_id) "
            "DO NOTHING"
        ),
        {"id": str(_GRANT_ID), "org_id": str(_ORG_ID)},
    )


def downgrade() -> None:
    # Reverse of upgrade: drop indexes, then the table (the unique constraint
    # lives on the table and is dropped implicitly with it; the seeded grant
    # row lives on the table and is dropped with it).
    op.drop_index("ix_role_grant_scope", table_name="role_grants")
    op.drop_index("ix_role_grant_principal", table_name="role_grants")
    op.drop_table("role_grants")
