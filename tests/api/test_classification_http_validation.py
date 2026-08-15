"""M4: HTTP-level classification wiring — /search filter + 422 on bad domain.

The provider-level search tests call HybridSearchProvider.query() directly,
bypassing the router's FastAPI query-param validation; these exercise the real
HTTP surface (domain narrowing through the router, and 422 rejection of an
out-of-enum domain on /search and /graph — /items already has that coverage).
"""

from __future__ import annotations

from k7e_api.models import ItemTag, KnowledgeItem, KnowledgeItemVersion


def _publish(session, slug, *, domain, tags=()):
    item = KnowledgeItem(slug=slug, title=slug, status="published", domain=domain)
    session.add(item)
    session.flush()
    ver = KnowledgeItemVersion(
        item_id=item.id,
        version_number=1,
        markdown_body=f"# {slug}\n\nretry policy content",
        model_id="t",
        created_by="t",
        citations=[],
        status="published",
        title=slug,
    )
    session.add(ver)
    session.flush()
    item.current_version_id = ver.id
    for tag in tags:
        session.add(ItemTag(item_id=item.id, tag=tag))


def _seed(sqlite_factory):
    with sqlite_factory() as s:
        _publish(s, "be", domain="backend", tags=["redis"])
        _publish(s, "fe", domain="frontend", tags=["redis"])
        s.commit()


def test_search_domain_filter_over_http(api_client, sqlite_factory):
    _seed(sqlite_factory)
    hits = api_client.get("/search?q=retry&domain=backend").json()["hits"]
    assert {h["slug"] for h in hits} == {"be"}


def test_search_tag_filter_over_http(api_client, sqlite_factory):
    _seed(sqlite_factory)
    hits = api_client.get("/search?q=retry&tag=redis&domain=frontend").json()["hits"]
    assert {h["slug"] for h in hits} == {"fe"}


def test_search_invalid_domain_returns_422(api_client, sqlite_factory):
    _seed(sqlite_factory)
    assert api_client.get("/search?q=retry&domain=bogus").status_code == 422


def test_graph_invalid_domain_returns_422(api_client, sqlite_factory):
    _seed(sqlite_factory)
    assert api_client.get("/graph?domain=bogus").status_code == 422
