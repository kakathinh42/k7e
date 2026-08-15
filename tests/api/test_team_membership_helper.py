"""M3 Step C: shared is_team_member helper resolves membership by team + user."""

from __future__ import annotations

import uuid

from k7e_api.models import Organization
from k7e_api.teams import is_team_member, provision_team

_ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")


def test_is_team_member_true_for_owner_false_for_stranger(sqlite_factory):
    with sqlite_factory() as s:
        s.add(Organization(id=_ORG, slug="test-org", name="Test Org"))
        s.flush()
        team = provision_team(s, slug="eng", name="Eng", owner_id="alice", org_id=_ORG)
        s.commit()
        assert is_team_member(s, team.id, "alice") is True
        assert is_team_member(s, team.id, "bob") is False
