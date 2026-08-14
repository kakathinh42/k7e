"""Space classification — the single source for a Space's user-facing "kind".

A Space is one of three kinds from the user's point of view:

- ``personal`` — a JIT-provisioned private space (``owner_user_id`` set); only
  its owner ever sees it.
- ``team`` — a Space owned by a ``Team``.
- ``public`` — the shared org corpus (everything else, e.g. "Engineering").
  "Public" here means org-wide/shared, not internet-public.

The frontend never re-derives this; it consumes the kind computed here.
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from k7e_api.models import Space, Team

SpaceKind = Literal["personal", "team", "public"]


def space_kind(space: Space, session: Session) -> SpaceKind:
    """Classify a single Space (see module docstring)."""
    if space.owner_user_id is not None:
        return "personal"
    owned_by_team = session.execute(
        select(Team.id).where(Team.space_id == space.id).limit(1)
    ).first()
    return "team" if owned_by_team is not None else "public"


def space_refs_for(space_ids: list, session: Session) -> dict:
    """Batch: ``{space_id: {"slug", "name", "kind"}}`` for the given space ids.

    Avoids N+1 when serializing a page of items — one query for the spaces and
    one for the team-owned set, then classify in memory.
    """
    ids = [sid for sid in {*space_ids} if sid is not None]
    if not ids:
        return {}
    spaces = session.execute(select(Space).where(Space.id.in_(ids))).scalars().all()
    team_owned = set(
        session.execute(select(Team.space_id).where(Team.space_id.in_(ids))).scalars()
    )
    result: dict = {}
    for sp in spaces:
        if sp.owner_user_id is not None:
            kind = "personal"
        elif sp.id in team_owned:
            kind = "team"
        else:
            kind = "public"
        result[sp.id] = {"slug": sp.slug, "name": sp.name, "kind": kind}
    return result
