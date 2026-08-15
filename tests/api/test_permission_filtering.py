"""Group-based retrieval filtering across /items, /search, /graph."""

from __future__ import annotations

from k7e_api.models import KnowledgeItem, KnowledgeItemVersion


def _publish(session, slug, title, item_type, *, allowed_groups=None, source_pages=None):
    item = KnowledgeItem(
        slug=slug,
        title=title,
        status="published",
        type=item_type,
        allowed_groups=allowed_groups,
        provenance={"resource": None, "source_pages": source_pages or []},
    )
    session.add(item)
    session.flush()
    ver = KnowledgeItemVersion(
        item_id=item.id,
        version_number=1,
        markdown_body=f"# {title}\n\nbody",
        model_id="t",
        created_by="t",
        citations=[],
        status="published",
        title=title,
    )
    session.add(ver)
    session.flush()
    item.current_version_id = ver.id
    return item


def _seed(sqlite_factory):
    with sqlite_factory() as s:
        _publish(s, "public-src", "Public Src", "source")
        _publish(s, "fin-src", "Finance Src", "source", allowed_groups=["finance"])
        _publish(
            s,
            "fin-concept",
            "Finance Concept",
            "concept",
            source_pages=["public-src", "fin-src"],
        )
        _publish(
            s,
            "public-concept",
            "Public Concept",
            "concept",
            source_pages=["public-src"],
        )
        s.commit()


def _slugs(resp):
    return {i["slug"] for i in resp.json()}


def test_public_items_visible_to_caller_without_groups(api_client, sqlite_factory):
    _seed(sqlite_factory)
    slugs = _slugs(api_client.get("/items"))
    assert "public-src" in slugs and "public-concept" in slugs
    assert "fin-src" not in slugs and "fin-concept" not in slugs


def test_finance_caller_sees_restricted(api_client, sqlite_factory):
    _seed(sqlite_factory)
    slugs = _slugs(api_client.get("/items", headers={"X-User-Groups": "finance"}))
    assert {"public-src", "fin-src", "fin-concept", "public-concept"} <= slugs


def test_restricted_source_hidden_from_other_group(api_client, sqlite_factory):
    _seed(sqlite_factory)
    slugs = _slugs(api_client.get("/items", headers={"X-User-Groups": "eng"}))
    assert "fin-src" not in slugs and "fin-concept" not in slugs


def test_get_item_404_for_restricted(api_client, sqlite_factory):
    _seed(sqlite_factory)
    assert api_client.get("/items/fin-src").status_code == 404
    assert (
        api_client.get("/items/fin-src", headers={"X-User-Groups": "finance"}).status_code == 200
    )


def test_derived_fail_safe_for_unresolvable_source(api_client, sqlite_factory):
    with sqlite_factory() as s:
        _publish(s, "ghost-concept", "Ghost", "concept", source_pages=["does-not-exist"])
        s.commit()
    assert "ghost-concept" not in _slugs(
        api_client.get("/items", headers={"X-User-Groups": "finance"})
    )


def test_graph_excludes_restricted(api_client, sqlite_factory):
    _seed(sqlite_factory)
    body = api_client.get("/graph").json()
    node_slugs = {n["slug"] for n in body["nodes"]}
    assert "fin-src" not in node_slugs and "fin-concept" not in node_slugs


def test_caller_allowed_nothing_sees_empty_not_everything(api_client, sqlite_factory):
    """Regression: an empty allowed-set must return NOTHING, never bypass to all.

    A caller matching no group, with zero public items, must get []. If any
    consumer ever switched `if allowed is not None` to a truthy check, the empty
    set would skip the filter and leak everything — this test would then fail.
    """
    with sqlite_factory() as s:
        _publish(s, "fin-only", "Fin Only", "source", allowed_groups=["finance"])
        _publish(s, "exec-only", "Exec Only", "source", allowed_groups=["exec"])
        s.commit()
    data = api_client.get("/items", headers={"X-User-Groups": "marketing"}).json()
    assert data == [], f"empty allowed-set must yield no items, got {data}"


def test_search_expansion_does_not_leak_restricted_neighbor(sqlite_factory):
    """Graph-expansion must not surface a restricted neighbour of a public hit."""
    from k7e_api.auth import GroupAuthorizationService, Principal
    from k7e_api.models import WikiLink
    from k7e_api.search import HybridSearchProvider

    with sqlite_factory() as s:
        pub = _publish(s, "public-hit", "Public Hit ZZUNIQUE", "source")
        fin = _publish(
            s,
            "fin-neighbor",
            "Finance Neighbor ZZUNIQUE",
            "source",
            allowed_groups=["finance"],
        )
        s.add(
            WikiLink(
                source_item_id=pub.id,
                target_item_id=fin.id,
                relation="related",
                score=0.9,
                origin="vector",
            )
        )
        s.commit()

    with sqlite_factory() as s:
        principal = Principal(user_id="u", roles=[], groups=[])  # no finance
        allowed = GroupAuthorizationService().allowed_item_ids(principal, s)
        hits = HybridSearchProvider().query(
            text="ZZUNIQUE",
            query_embedding=[],
            allowed_ids=allowed,
            limit=10,
            session=s,
        )
    slugs = {h.slug for h in hits}
    assert "public-hit" in slugs, "the public hit should be returned"
    assert "fin-neighbor" not in slugs, "restricted neighbour must NOT leak via expansion"


def test_search_http_excludes_restricted_item(api_client, sqlite_factory):
    """HTTP GET /search must honour group-based permission filtering.

    A public item and a finance-restricted item are seeded with a shared
    unique keyword.  An unauthorized caller must see only the public item;
    an authorized caller (finance group) must also see the restricted item.

    This test locks the HTTP wiring so that any future regression in the
    search route's authz plumbing is caught immediately.
    """
    from k7e_api.deps import get_embedding_client
    from k7e_api.embedding_client import StubEmbeddingClient
    from k7e_api.main import app

    with sqlite_factory() as s:
        _publish(s, "pub-doc", "Public ZZSECRET", "source")
        _publish(s, "fin-doc", "Finance ZZSECRET", "source", allowed_groups=["finance"])
        s.commit()

    app.dependency_overrides[get_embedding_client] = lambda: StubEmbeddingClient()
    try:
        # Unauthorized caller: no finance group → restricted item must be absent.
        resp = api_client.get("/search", params={"q": "ZZSECRET"})
        assert resp.status_code == 200, resp.text
        hits = resp.json()["hits"]
        slugs = {h["slug"] for h in hits}
        assert "pub-doc" in slugs, f"public item must appear in results, got {slugs}"
        assert "fin-doc" not in slugs, (
            f"restricted item must be absent for unauthorized caller, got {slugs}"
        )

        # Authorized caller: finance group → restricted item must be present.
        resp2 = api_client.get(
            "/search",
            params={"q": "ZZSECRET"},
            headers={"X-User-Groups": "finance"},
        )
        assert resp2.status_code == 200, resp2.text
        hits2 = resp2.json()["hits"]
        slugs2 = {h["slug"] for h in hits2}
        assert "fin-doc" in slugs2, f"restricted item must appear for finance caller, got {slugs2}"
    finally:
        app.dependency_overrides.pop(get_embedding_client, None)
