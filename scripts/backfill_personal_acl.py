#!/usr/bin/env python
"""Backfill allowed_groups=["user:<owner>"] on personal-space items missing it.

Remediates rows created before the mirror stamped personal-space ACLs (the
cross-user leak fix). Idempotent — only touches owned-space items whose
allowed_groups is NULL.

Usage:
    DATABASE_URL=postgresql+psycopg://wiki:wiki@localhost:5435/wiki \
        python scripts/backfill_personal_acl.py
"""

from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from k7e_api.config import get_settings
from k7e_api.models import KnowledgeItem, Space


def backfill(session: Session) -> int:
    # allowed_groups is a JSON column: on SQLite, SQLAlchemy stores Python
    # ``None`` as the JSON literal ``'null'`` rather than SQL NULL, so a
    # SQL-level ``allowed_groups.is_(None)`` predicate silently matches
    # nothing there (Postgres' native JSON type does map None -> SQL NULL,
    # so this only bites the SQLite test DB, not production) — matching
    # rbac.py/auth.py, which likewise never filter allowed_groups in SQL and
    # instead check the fetched Python value. Filter in Python here too, for
    # a check that is correct on both backends.
    rows = session.execute(
        select(KnowledgeItem, Space.owner_user_id)
        .join(Space, Space.id == KnowledgeItem.space_id)
        .where(Space.owner_user_id.is_not(None))
    ).all()
    n = 0
    for item, owner in rows:
        if item.allowed_groups is not None:
            continue
        item.allowed_groups = [f"user:{owner}"]
        n += 1
    session.commit()
    return n


def main() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        n = backfill(session)
        print(f"backfilled {n} personal-space item(s)")


if __name__ == "__main__":
    main()
