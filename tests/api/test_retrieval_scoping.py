"""Permission-aware retrieval: /search and /items scoped to the delegated
on-behalf identity via ``get_effective_principal_with_teams``.

A delegated caller (valid X-App-Key for a can_delegate_identity app +
X-On-Behalf-Of-Email) must see ONLY: their personal-space items
(allowed_groups=["user:<email>"]) + their team items + org-public items --
never another user's private items. A non-delegated caller (no app key)
degrades to the normal (anonymous, in prod) principal -- public-only, and
must never 403.

Modeled on the delegated-app seeding in test_ingest_conversation_delegated.py
and the item/allowed_groups RBAC seeding in test_space_filter.py.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from k7e_api.app_auth import generate_app_key
from k7e_api.auth import get_authz
from k7e_api.main import app
from k7e_api.models import (
    ClientApp,
    KnowledgeItem,
    KnowledgeItemVersion,
    Membership,
    RoleGrant,
)
from k7e_api.rbac import HierarchicalRbacAuthorizationService
from k7e_api.teams import provision_team
from sqlalchemy import select

from tests.api.conftest import TEST_TENANT_CONTEXT

_ORG = TEST_TENANT_CONTEXT.org_id


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _publish(session, *, slug, allowed_groups=None, term) -> KnowledgeItem:
    """Seed a published source item whose body contains ``term`` (org_id is
    defaulted to the test org by the conftest RBAC-seeding hook)."""
    item = KnowledgeItem(
        slug=slug,
        title=slug,
        status="published",
        type="source",
        allowed_groups=allowed_groups,
        provenance={"resource": None, "source_pages": []},
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(item)
    session.flush()
    version = KnowledgeItemVersion(
        item_id=item.id,
        version_number=1,
        markdown_body=f"# {slug}\n\nnotes about {term}",
        model_id="t",
        created_by="t",
        citations=[],
        status="published",
        title=slug,
        created_at=_now(),
    )
    session.add(version)
    session.flush()
    item.current_version_id = version.id
    return item


def _seed_personal_item(sqlite_factory, email: str, *, term: str) -> None:
    with sqlite_factory() as s:
        _publish(s, slug=f"item-{term}", allowed_groups=[f"user:{email}"], term=term)
        s.commit()


def _seed_team_item(sqlite_factory, *, team_slug: str, term: str) -> None:
    with sqlite_factory() as s:
        _publish(s, slug=f"item-{term}", allowed_groups=[f"team:{team_slug}"], term=term)
        s.commit()


def _seed_delegation_app(sqlite_factory) -> str:
    """Seed a delegation-allowed ClientApp in the test org; return the plaintext key."""
    with sqlite_factory() as s:
        plaintext, key_hash = generate_app_key()
        s.add(
            ClientApp(
                org_id=_ORG,
                slug="chat-agent",
                name="Chat Agent",
                api_key_hash=key_hash,
                can_delegate_identity=True,
            )
        )
        s.commit()
        return plaintext


def _seed_team_membership(sqlite_factory, *, slug: str, user_id: str) -> None:
    with sqlite_factory() as s:
        team = provision_team(s, slug=slug, name=slug, owner_id="owner-x", org_id=_ORG)
        s.add(Membership(team_id=team.id, user_id=user_id, role="member"))
        s.commit()


# ---------------------------------------------------------------------------
# 1. A delegated caller sees only their own personal item, never another
#    user's.
# ---------------------------------------------------------------------------


def test_search_scoped_to_delegated_user(api_client, sqlite_factory):
    _seed_personal_item(sqlite_factory, "alice@example.com", term="alphasecret")
    _seed_personal_item(sqlite_factory, "bob@example.com", term="betasecret")
    key = _seed_delegation_app(sqlite_factory)
    h = {"X-App-Key": key, "X-On-Behalf-Of-Email": "alice@example.com"}

    alice_hits = api_client.get("/search", params={"q": "alphasecret"}, headers=h).json()["hits"]
    assert {hit["slug"] for hit in alice_hits} == {"item-alphasecret"}

    bob_hits = api_client.get("/search", params={"q": "betasecret"}, headers=h).json()["hits"]
    assert bob_hits == []


def test_items_scoped_to_delegated_user(api_client, sqlite_factory):
    _seed_personal_item(sqlite_factory, "alice@example.com", term="alphasecret")
    _seed_personal_item(sqlite_factory, "bob@example.com", term="betasecret")
    key = _seed_delegation_app(sqlite_factory)
    h = {"X-App-Key": key, "X-On-Behalf-Of-Email": "alice@example.com"}

    data = api_client.get("/items", headers=h).json()
    assert {i["slug"] for i in data} == {"item-alphasecret"}


# ---------------------------------------------------------------------------
# 2. No delegation (no X-App-Key) -> anonymous/public-only, never 403.
# ---------------------------------------------------------------------------


def test_no_delegation_sees_public_only(api_client, sqlite_factory):
    _seed_personal_item(sqlite_factory, "alice@example.com", term="alphasecret")
    # no X-App-Key -> not delegated -> anonymous/public-only, never 403
    r = api_client.get("/search", params={"q": "alphasecret"})
    assert r.status_code == 200
    assert r.json()["hits"] == []


def test_no_delegation_items_sees_public_only(api_client, sqlite_factory):
    _seed_personal_item(sqlite_factory, "alice@example.com", term="alphasecret")
    r = api_client.get("/items")
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# 3. Team visibility: a delegated team:eng member sees the team item; a
#    delegated non-member does not.
# ---------------------------------------------------------------------------


def test_delegated_team_member_sees_team_item(api_client, sqlite_factory):
    _seed_team_item(sqlite_factory, team_slug="eng", term="teamsecret")
    _seed_team_membership(sqlite_factory, slug="eng", user_id="alice@example.com")
    key = _seed_delegation_app(sqlite_factory)
    h = {"X-App-Key": key, "X-On-Behalf-Of-Email": "alice@example.com"}

    hits = api_client.get("/search", params={"q": "teamsecret"}, headers=h).json()["hits"]
    assert {hit["slug"] for hit in hits} == {"item-teamsecret"}


def test_delegated_non_member_does_not_see_team_item(api_client, sqlite_factory):
    _seed_team_item(sqlite_factory, team_slug="eng", term="teamsecret")
    # bob has no Membership in team eng
    key = _seed_delegation_app(sqlite_factory)
    h = {"X-App-Key": key, "X-On-Behalf-Of-Email": "bob@example.com"}

    hits = api_client.get("/search", params={"q": "teamsecret"}, headers=h).json()["hits"]
    assert hits == []


# ---------------------------------------------------------------------------
# 4. Archive (DELETE) is NOT delegatable — it is a destructive write, kept on
#    get_principal_with_teams (not the delegated resolver). A delegated
#    chat-agent cannot archive an item on a user's behalf.
# ---------------------------------------------------------------------------


@pytest.fixture()
def gated_client(api_client, sqlite_factory):
    """``api_client`` with ``get_authz`` bound to the test DB.

    The default ``get_authz()`` service opens ``SessionLocal`` (the production
    engine) for its grant walks, so test-seeded grants are invisible to
    ``can_write``. Binding the RBAC service to the test ``sqlite_factory`` makes
    grant-based write gating exercisable through HTTP — this is what gives the
    archive-delegation test its teeth (the editor grant that WOULD let a
    delegated alice archive, if archive honored delegation). Mirrors the
    ``gated_client`` fixture in test_rbac_write_gating.py.
    """
    app.dependency_overrides[get_authz] = lambda: HierarchicalRbacAuthorizationService(
        session_factory=sqlite_factory
    )
    yield api_client
    app.dependency_overrides.pop(get_authz, None)


def test_archive_not_delegatable(gated_client, sqlite_factory, monkeypatch):
    """A delegated chat-agent (X-App-Key + X-On-Behalf-Of-Email) issuing
    DELETE /items/<slug> is refused (403) and the item survives.

    Archive stays on ``get_principal_with_teams``, so the on-behalf headers are
    ignored: the app-key-only caller resolves through ``get_principal`` to the
    normal principal (anonymous outside dev), which holds no editor grant, so
    the write gate returns 403. Forcing ``ENV=prod`` exercises that anonymous
    path (in dev, ``get_principal`` would fall back to the dev/reviewer
    identity, masking the boundary).

    Teeth: alice holds an org-wide editor grant and ``get_authz`` is bound to
    the test DB (``gated_client``), so IF archive honored the delegated
    identity, alice-as-editor would archive the item (200). Because archive is
    NOT delegated, the resolved caller is anonymous (public viewer only) and is
    refused (403) — the item is left published. (Verified during authoring:
    flipping archive to the delegated resolver turns this into a 200.)
    """
    from k7e_api.config import get_settings

    monkeypatch.setenv("ENV", "prod")
    get_settings.cache_clear()
    try:
        # A public item alice could otherwise read, plus an org editor grant.
        with sqlite_factory() as s:
            _publish(s, slug="item-public", allowed_groups=None, term="publicterm")
            s.add(
                RoleGrant(
                    principal_kind="user",
                    principal_id="alice@example.com",
                    role="editor",
                    scope_kind="org",
                    scope_id=_ORG,
                )
            )
            s.commit()
        key = _seed_delegation_app(sqlite_factory)
        h = {"X-App-Key": key, "X-On-Behalf-Of-Email": "alice@example.com"}

        resp = gated_client.delete("/items/item-public", headers=h)
        assert resp.status_code == 403, resp.text
    finally:
        get_settings.cache_clear()

    # The item is untouched — still published, not archived.
    with sqlite_factory() as s:
        item = s.execute(
            select(KnowledgeItem).where(KnowledgeItem.slug == "item-public")
        ).scalar_one()
        assert item.status == "published"
