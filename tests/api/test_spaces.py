"""space_kind — the single source for a Space's user-facing kind."""

from __future__ import annotations

import uuid

from k7e_api.models import Organization, Space
from k7e_api.personal_spaces import provision_personal_space
from k7e_api.spaces import space_kind
from k7e_api.teams import provision_team

_ORG_ID = uuid.UUID("00000000-0000-0000-0000-0000000000f2")


def _org(s):
    s.add(Organization(id=_ORG_ID, slug="spaces-org", name="Spaces Org"))
    s.commit()


def test_space_kind_personal(sqlite_factory):
    with sqlite_factory() as s:
        _org(s)
        space = provision_personal_space(s, user_id="alice", org_id=_ORG_ID)
        assert space_kind(space, s) == "personal"


def test_space_kind_team(sqlite_factory):
    with sqlite_factory() as s:
        _org(s)
        team = provision_team(
            s, slug="platform", name="Platform", owner_id="alice", org_id=_ORG_ID
        )
        space = s.get(Space, team.space_id)
        assert space_kind(space, s) == "team"


def test_space_kind_public(sqlite_factory):
    with sqlite_factory() as s:
        _org(s)
        space = Space(org_id=_ORG_ID, slug="engineering", name="Engineering", visibility="members")
        s.add(space)
        s.commit()
        assert space_kind(space, s) == "public"
