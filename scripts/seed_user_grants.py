#!/usr/bin/env python
"""Seed an org-scope RoleGrant for a pilot user identity (idempotent).

Logged-in ≠ authorized: a JWT-verified principal has no roles until granted
(`Principal.roles == []`; RBAC walks `role_grants`). This gives a pilot
identity a role at org scope so org-level writes/review work. Personal-space
ingest does NOT need this — JIT provisioning grants the owner directly.

Usage (host, against the compose Postgres):
    DATABASE_URL=postgresql+psycopg://wiki:wiki@localhost:5435/wiki \
        python scripts/seed_user_grants.py --user alice --role editor
"""

from __future__ import annotations

import argparse

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from k7e_api.config import get_settings
from k7e_api.models import Organization, RoleGrant


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", required=True, help="identity-claim value (JWT sub)")
    parser.add_argument(
        "--role", default="editor", choices=["viewer", "editor", "reviewer", "admin"]
    )
    parser.add_argument("--org", default="", help="org slug (default: settings)")
    args = parser.parse_args()

    settings = get_settings()
    org_slug = args.org or settings.default_org_slug
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        org = session.execute(
            select(Organization).where(Organization.slug == org_slug)
        ).scalar_one_or_none()
        if org is None:
            raise SystemExit(f"org {org_slug!r} not found")
        existing = session.execute(
            select(RoleGrant).where(
                RoleGrant.principal_kind == "user",
                RoleGrant.principal_id == args.user,
                RoleGrant.role == args.role,
                RoleGrant.scope_kind == "org",
                RoleGrant.scope_id == org.id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            print(f"grant already present: {args.user} {args.role}@org:{org_slug}")
            return
        session.add(
            RoleGrant(
                principal_kind="user",
                principal_id=args.user,
                role=args.role,
                scope_kind="org",
                scope_id=org.id,
            )
        )
        session.commit()
        print(f"granted: {args.user} {args.role}@org:{org_slug}")


if __name__ == "__main__":
    main()
