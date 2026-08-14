"""get_effective_principal_with_teams: delegated principal + team groups."""

from __future__ import annotations

from k7e_api.app_auth import generate_app_key, get_effective_principal_with_teams
from k7e_api.auth import Principal
from k7e_api.models import ClientApp, Membership, Organization, Space, Team


def _seed(session, *, delegate=True):
    org = Organization(slug="o", name="O")
    session.add(org)
    session.flush()
    plaintext, key_hash = generate_app_key()
    session.add(
        ClientApp(
            org_id=org.id,
            slug="chat-agent",
            name="CA",
            api_key_hash=key_hash,
            can_delegate_identity=delegate,
        )
    )
    # Team.space_id is NOT NULL: every team owns a members-only Space.
    space = Space(org_id=org.id, slug="team-eng", name="Eng space")
    session.add(space)
    session.flush()
    team = Team(org_id=org.id, space_id=space.id, slug="eng", name="Eng", created_by="owner-x")
    session.add(team)
    session.flush()
    session.add(Membership(team_id=team.id, user_id="alice@example.com", role="member"))
    session.commit()
    return plaintext


def test_delegated_principal_gets_team_groups(sqlite_factory):
    # get_effective_principal_with_teams takes (session, principal); the delegated
    # principal is produced by get_effective_principal upstream. Call it directly
    # with a pre-built delegated Principal to isolate the team-union behavior.
    with sqlite_factory() as session:
        _seed(session)
        delegated = Principal(kind="user", user_id="alice@example.com", roles=[], verified=True)
        p = get_effective_principal_with_teams(session=session, principal=delegated)
        assert "team:eng" in p.groups
        assert p.user_id == "alice@example.com"


def test_no_teams_returns_principal_unchanged(sqlite_factory):
    with sqlite_factory() as session:
        _seed(session)
        delegated = Principal(kind="user", user_id="bob@example.com", roles=[], verified=True)
        p = get_effective_principal_with_teams(session=session, principal=delegated)
        assert p.groups == []  # bob has no memberships
