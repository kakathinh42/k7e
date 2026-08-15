"""Task 10: ``space`` filter on GET /search and GET /items.

Mirrors the M4 ``domain`` filter pattern exactly (see
test_items_classification_filter.py / test_search_classification_filter.py):
an optional FastAPI Query param resolves an org-scoped slug to a Space row,
whose id is pushed into both the item-listing statement and the search
provider's ``query()`` (a ``space_id`` param threaded like ``domain``).

Read-path guardrail: ``space=personal`` resolves through
``personal_space_for`` (the caller's EXISTING personal space only) — it must
NEVER provision one (no JIT on a read path). Unknown/absent slugs 404. RBAC
(``allowed_item_ids``) is applied first; the space filter only narrows the
admitted set, so it can never widen visibility (locked by the "bob requests
alice's personal space" case below).
"""

from __future__ import annotations

from datetime import datetime, timezone

from k7e_api.models import KnowledgeItem, KnowledgeItemVersion, Space
from sqlalchemy import select

from tests.api.conftest import TEST_TENANT_CONTEXT

_ORG = TEST_TENANT_CONTEXT.org_id


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _publish(session, *, slug, allowed_groups=None, space_id=None) -> KnowledgeItem:
    """Seed a published source item; org_id is defaulted by the conftest hook."""
    item = KnowledgeItem(
        slug=slug,
        title=slug,
        status="published",
        type="source",
        allowed_groups=allowed_groups,
        space_id=space_id,
        provenance={"resource": None, "source_pages": []},
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(item)
    session.flush()
    version = KnowledgeItemVersion(
        item_id=item.id,
        version_number=1,
        markdown_body=f"# {slug}\n\nnotes about apples",
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


def _seed(sqlite_factory) -> None:
    """A legacy default-bundle item, a team-space item, and alice's personal item."""
    with sqlite_factory() as s:
        team = Space(org_id=_ORG, slug="team-eng", name="Engineering")
        alice_space = Space(
            org_id=_ORG,
            slug="user-alice",
            name="Personal - alice",
            owner_user_id="alice",
        )
        s.add_all([team, alice_space])
        s.flush()
        _publish(s, slug="default-item", space_id=None)
        _publish(s, slug="team-item", space_id=team.id)
        _publish(
            s,
            slug="alice-item",
            space_id=alice_space.id,
            allowed_groups=["user:alice"],
        )
        s.commit()


# ---------------------------------------------------------------------------
# 1. No `space` param -> merged/default results unchanged (regression lock).
# ---------------------------------------------------------------------------


def test_items_no_space_param_unchanged(api_client, sqlite_factory):
    _seed(sqlite_factory)
    data = api_client.get("/items").json()
    assert {i["slug"] for i in data} == {"default-item", "team-item"}


def test_search_no_space_param_unchanged(api_client, sqlite_factory):
    _seed(sqlite_factory)
    hits = api_client.get("/search?q=apples").json()["hits"]
    assert {h["slug"] for h in hits} == {"default-item", "team-item"}


# ---------------------------------------------------------------------------
# 2. space=<team-or-org slug> -> narrows to only that space's items.
# ---------------------------------------------------------------------------


def test_items_space_slug_narrows(api_client, sqlite_factory):
    _seed(sqlite_factory)
    data = api_client.get("/items?space=team-eng").json()
    assert {i["slug"] for i in data} == {"team-item"}


def test_search_space_slug_narrows(api_client, sqlite_factory):
    _seed(sqlite_factory)
    hits = api_client.get("/search?q=apples&space=team-eng").json()["hits"]
    assert {h["slug"] for h in hits} == {"team-item"}


# ---------------------------------------------------------------------------
# 3. space=personal as alice -> only her personal items.
# ---------------------------------------------------------------------------


def test_items_space_personal_as_alice(api_client, sqlite_factory):
    _seed(sqlite_factory)
    data = api_client.get("/items?space=personal", headers={"X-User-Id": "alice"}).json()
    assert {i["slug"] for i in data} == {"alice-item"}


def test_search_space_personal_as_alice(api_client, sqlite_factory):
    _seed(sqlite_factory)
    hits = api_client.get(
        "/search?q=apples&space=personal", headers={"X-User-Id": "alice"}
    ).json()["hits"]
    assert {h["slug"] for h in hits} == {"alice-item"}


# ---------------------------------------------------------------------------
# 4. Visibility never widens: bob + space=<alice's slug> -> 200 [] (RBAC
#    hides her content -- not a 403, and not alice's items).
# ---------------------------------------------------------------------------


def test_items_space_visibility_never_widens(api_client, sqlite_factory):
    _seed(sqlite_factory)
    resp = api_client.get("/items?space=user-alice", headers={"X-User-Id": "bob"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_search_space_visibility_never_widens(api_client, sqlite_factory):
    _seed(sqlite_factory)
    resp = api_client.get("/search?q=apples&space=user-alice", headers={"X-User-Id": "bob"})
    assert resp.status_code == 200
    assert resp.json()["hits"] == []


# ---------------------------------------------------------------------------
# 5. space=<unknown slug> -> 404.
# ---------------------------------------------------------------------------


def test_items_unknown_space_404(api_client, sqlite_factory):
    _seed(sqlite_factory)
    resp = api_client.get("/items?space=does-not-exist")
    assert resp.status_code == 404


def test_search_unknown_space_404(api_client, sqlite_factory):
    _seed(sqlite_factory)
    resp = api_client.get("/search?q=apples&space=does-not-exist")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 6. space=personal with no personal space yet -> 404, no JIT side effect.
# ---------------------------------------------------------------------------


def test_items_space_personal_no_space_404_no_jit(api_client, sqlite_factory):
    _seed(sqlite_factory)
    resp = api_client.get("/items?space=personal", headers={"X-User-Id": "bob"})
    assert resp.status_code == 404
    with sqlite_factory() as s:
        rows = s.execute(select(Space).where(Space.owner_user_id == "bob")).scalars().all()
        assert rows == []


def test_search_space_personal_no_space_404_no_jit(api_client, sqlite_factory):
    _seed(sqlite_factory)
    resp = api_client.get("/search?q=apples&space=personal", headers={"X-User-Id": "bob"})
    assert resp.status_code == 404
    with sqlite_factory() as s:
        rows = s.execute(select(Space).where(Space.owner_user_id == "bob")).scalars().all()
        assert rows == []


# ---------------------------------------------------------------------------
# 7. GET /graph honours the same ``space`` filter (private / team / public
#    graph views), applied after RBAC so it only ever narrows.
# ---------------------------------------------------------------------------


def _graph_slugs(api_client, query: str = "") -> set[str]:
    body = api_client.get(f"/graph{query}").json()
    return {n["slug"] for n in body["nodes"]}


def test_graph_no_space_param_unchanged(api_client, sqlite_factory):
    _seed(sqlite_factory)
    assert _graph_slugs(api_client) == {"default-item", "team-item"}


def test_graph_space_slug_narrows(api_client, sqlite_factory):
    _seed(sqlite_factory)
    assert _graph_slugs(api_client, "?space=team-eng") == {"team-item"}


def test_graph_space_personal_as_alice(api_client, sqlite_factory):
    _seed(sqlite_factory)
    body = api_client.get("/graph?space=personal", headers={"X-User-Id": "alice"}).json()
    assert {n["slug"] for n in body["nodes"]} == {"alice-item"}


def test_graph_space_visibility_never_widens(api_client, sqlite_factory):
    _seed(sqlite_factory)
    resp = api_client.get("/graph?space=user-alice", headers={"X-User-Id": "bob"})
    assert resp.status_code == 200
    assert resp.json()["nodes"] == []


def test_graph_unknown_space_404(api_client, sqlite_factory):
    _seed(sqlite_factory)
    resp = api_client.get("/graph?space=does-not-exist")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 8. GET /search accepts a REPEATED ``?space=`` — the union of those spaces
#    (backs the MCP list_wiki_spaces + multi-team scoped search).
# ---------------------------------------------------------------------------


def test_search_multiple_spaces_union_as_alice(api_client, sqlite_factory):
    _seed(sqlite_factory)
    hits = api_client.get(
        "/search?q=apples&space=team-eng&space=personal",
        headers={"X-User-Id": "alice"},
    ).json()["hits"]
    # union of the team space + alice's personal space
    assert {h["slug"] for h in hits} == {"team-item", "alice-item"}


def test_search_unknown_space_in_list_404(api_client, sqlite_factory):
    _seed(sqlite_factory)
    resp = api_client.get("/search?q=apples&space=team-eng&space=nope")
    assert resp.status_code == 404


def test_search_multi_space_never_widens(api_client, sqlite_factory):
    """bob naming alice's space in the union still can't see her items."""
    _seed(sqlite_factory)
    hits = api_client.get(
        "/search?q=apples&space=team-eng&space=user-alice",
        headers={"X-User-Id": "bob"},
    ).json()["hits"]
    assert {h["slug"] for h in hits} == {"team-item"}  # alice-item stays hidden
