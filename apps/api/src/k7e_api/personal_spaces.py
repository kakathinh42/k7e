"""JIT provisioning of personal Spaces (personal-spaces spec Piece 2).

A personal space is a bare Space with owner_user_id set and two direct user
grants (editor + admin). No Team, no Membership, no group — /teams stays clean.
"""

from __future__ import annotations

import hashlib
import re
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from k7e_api.models import RoleGrant, Space


def _slugify_sub(sub: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", sub.lower()).strip("-") or "user"
    return f"user-{base}"[:120]


def personal_space_for(session: Session, *, user_id: str, org_id: uuid.UUID) -> Space | None:
    return session.execute(
        select(Space).where(Space.org_id == org_id, Space.owner_user_id == user_id)
    ).scalar_one_or_none()


def resolve_space_filter(
    session: Session, *, space_slug: str, user_id: str, org_id: uuid.UUID
) -> Space | None:
    """Resolve a ``space=`` read-filter slug to a Space row — no JIT.

    ``"personal"`` looks up the caller's EXISTING personal space via
    ``personal_space_for`` and returns ``None`` when they don't have one yet
    — a read-path filter must never provision a space as a side effect (that
    is why this does not call ``provision_personal_space`` or
    ``require_verified_identity``). Any other slug is a plain org-scoped
    lookup. ``None`` means "does not resolve"; the caller (a router) turns
    that into a 404.
    """
    if space_slug == "personal":
        return personal_space_for(session, user_id=user_id, org_id=org_id)
    return session.execute(
        select(Space).where(Space.org_id == org_id, Space.slug == space_slug)
    ).scalar_one_or_none()


def provision_personal_space(session: Session, *, user_id: str, org_id: uuid.UUID) -> Space:
    existing = personal_space_for(session, user_id=user_id, org_id=org_id)
    if existing is not None:
        return existing

    slug = _slugify_sub(user_id)
    if (
        session.execute(
            select(Space.id).where(Space.org_id == org_id, Space.slug == slug)
        ).scalar_one_or_none()
        is not None
    ):
        # Two subs slugifying identically — disambiguate with a hash suffix.
        slug = f"{slug}-{hashlib.sha256(user_id.encode()).hexdigest()[:6]}"

    space = Space(
        org_id=org_id,
        slug=slug,
        name=f"Personal — {user_id}",
        visibility="members",
        owner_user_id=user_id,
    )
    session.add(space)
    try:
        session.flush()
    except IntegrityError:
        # Concurrent first ingest: loser re-reads the winner's row.
        session.rollback()
        won = personal_space_for(session, user_id=user_id, org_id=org_id)
        if won is None:
            raise
        return won
    for role in ("editor", "admin"):
        session.add(
            RoleGrant(
                principal_kind="user",
                principal_id=user_id,
                role=role,
                scope_kind="space",
                scope_id=space.id,
            )
        )
    session.flush()
    return space
