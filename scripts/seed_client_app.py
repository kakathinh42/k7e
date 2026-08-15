#!/usr/bin/env python
"""Provision (or update) a ClientApp with identity delegation enabled — idempotent.

A ClientApp authenticates via ``X-App-Key`` (only the sha256 hash is stored).
For the trusted-subsystem flow, the app must also carry ``can_delegate_identity``
so it may assert an end user via ``X-On-Behalf-Of-Email`` (see
``app_auth.get_effective_principal``). The ``POST /apps`` API does NOT expose the
delegation flags, so enable them here.

Create-or-update semantics (keyed on the api-key hash, then org+slug):
  * existing app (same key)      → flip on delegation / domain, ensure role grant
  * existing slug, different key → realign its key hash + delegation (local dev)
  * none                         → create the app + an org-scope editor grant

Usage (host, against the compose Postgres on the shifted port 5435):

    DATABASE_URL=postgresql+psycopg://wiki:wiki@localhost:5435/wiki \
        python scripts/seed_client_app.py \
            --key wapp_uqz8g-M3X0jQWUbRohFe1ZLlXnjPodrEjXjAgNG6NL8 \
            --slug chat-agent --name "Chat Agent"

Add ``--domain example.com`` to restrict which email domain the app may assert
(prod posture). Omit it for local (NULL = no domain guard). Pass ``--no-delegate``
to provision the app WITHOUT delegation.
"""

from __future__ import annotations

import argparse

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from k7e_api.app_auth import hash_app_key
from k7e_api.config import get_settings
from k7e_api.models import ClientApp, Organization, RoleGrant


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    key_group = parser.add_mutually_exclusive_group(required=True)
    key_group.add_argument("--key", help="plaintext app key (wapp_...); hashed here")
    key_group.add_argument("--key-hash", help="precomputed sha256 hex of the app key")
    parser.add_argument("--slug", default="chat-agent", help="app slug / principal id")
    parser.add_argument("--name", default="Chat Agent", help="human-readable name")
    parser.add_argument("--org", default="", help="org slug (default: settings)")
    parser.add_argument(
        "--domain",
        default=None,
        help="allowed_identity_domain guard (e.g. example.com); omit = no guard",
    )
    parser.add_argument(
        "--no-delegate",
        action="store_true",
        help="provision WITHOUT can_delegate_identity (default: delegation ON)",
    )
    args = parser.parse_args()

    key_hash = args.key_hash or hash_app_key(args.key)
    can_delegate = not args.no_delegate

    settings = get_settings()
    org_slug = args.org or settings.default_org_slug
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        org = session.execute(
            select(Organization).where(Organization.slug == org_slug)
        ).scalar_one_or_none()
        if org is None:
            raise SystemExit(f"org {org_slug!r} not found — bring up k7e first")

        # 1) Locate by key hash (the identity that actually matters), else by
        #    (org, slug) — the unique constraint.
        app = session.execute(
            select(ClientApp).where(ClientApp.api_key_hash == key_hash)
        ).scalar_one_or_none()
        by_hash = app is not None
        if app is None:
            app = session.execute(
                select(ClientApp).where(
                    ClientApp.org_id == org.id, ClientApp.slug == args.slug
                )
            ).scalar_one_or_none()

        if app is None:
            app = ClientApp(
                org_id=org.id,
                slug=args.slug,
                name=args.name,
                api_key_hash=key_hash,
                can_delegate_identity=can_delegate,
                allowed_identity_domain=args.domain,
            )
            session.add(app)
            action = "created"
        else:
            if not by_hash and app.api_key_hash != key_hash:
                print(
                    f"warning: slug {app.slug!r} existed with a different key — "
                    "realigning its api_key_hash to the provided key"
                )
                app.api_key_hash = key_hash
            app.can_delegate_identity = can_delegate
            app.allowed_identity_domain = args.domain
            action = "updated"

        session.flush()  # ensure app.id / org linkage before the grant lookup

        # 2) Ensure the org-scope editor grant POST /apps would have created, so
        #    the non-delegated /ingest/source (org-public) path also works.
        grant = session.execute(
            select(RoleGrant).where(
                RoleGrant.principal_kind == "app",
                RoleGrant.principal_id == app.slug,
                RoleGrant.role == "editor",
                RoleGrant.scope_kind == "org",
                RoleGrant.scope_id == org.id,
            )
        ).scalar_one_or_none()
        if grant is None:
            session.add(
                RoleGrant(
                    principal_kind="app",
                    principal_id=app.slug,
                    role="editor",
                    scope_kind="org",
                    scope_id=org.id,
                )
            )
            grant_note = "editor@org grant added"
        else:
            grant_note = "editor@org grant already present"

        session.commit()

    domain_note = args.domain or "(no domain guard)"
    print(
        f"{action}: app {args.slug!r}@org:{org_slug} "
        f"can_delegate_identity={can_delegate} domain={domain_note}; {grant_note}"
    )


if __name__ == "__main__":
    main()
