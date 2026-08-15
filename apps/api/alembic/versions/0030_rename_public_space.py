"""Rename the seeded public space "Engineering" → "Public".

The org-wide shared corpus (slug ``engineering``, seeded in 0016) is the
``public`` Space in the space model, so its display name should read "Public"
rather than the arbitrary "Engineering". Data-only and reversible: downgrade
restores "Engineering". The ``slug`` is intentionally left unchanged — it is a
stable identifier used by the ``?space=`` filters and space tabs.

Revision ID: 0030_rename_public_space
Revises: 0029_drop_login_codes
"""

from __future__ import annotations

from alembic import op

revision: str = "0030_rename_public_space"
down_revision: str | None = "0029_drop_login_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Scope to the org-wide public space only (no owner) — never a personal or
    # team space that might coincidentally be named "Engineering".
    op.execute(
        "UPDATE spaces SET name = 'Public' "
        "WHERE slug = 'engineering' AND owner_user_id IS NULL "
        "AND name = 'Engineering'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE spaces SET name = 'Engineering' "
        "WHERE slug = 'engineering' AND owner_user_id IS NULL "
        "AND name = 'Public'"
    )
