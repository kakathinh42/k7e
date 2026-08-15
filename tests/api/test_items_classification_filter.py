"""M4: GET /items ?domain= & ?tag= filters + ItemSummary domain/tags."""

from __future__ import annotations

from k7e_api.models import ItemTag, KnowledgeItem, KnowledgeItemVersion


def _publish(session, slug, *, domain=None, tags=()):
    item = KnowledgeItem(slug=slug, title=slug, status="published", domain=domain)
    session.add(item)
    session.flush()
    ver = KnowledgeItemVersion(
        item_id=item.id,
        version_number=1,
        markdown_body=f"# {slug}\n\nbody",
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
        _publish(s, "be-1", domain="backend", tags=["redis", "cache"])
        _publish(s, "be-2", domain="backend", tags=["redis"])
        _publish(s, "fe-1", domain="frontend", tags=["react"])
        s.commit()


def test_filter_by_domain(api_client, sqlite_factory):
    _seed(sqlite_factory)
    data = api_client.get("/items?domain=backend").json()
    assert {i["slug"] for i in data} == {"be-1", "be-2"}
    assert all(i["domain"] == "backend" for i in data)


def test_unknown_domain_rejected(api_client, sqlite_factory):
    _seed(sqlite_factory)
    assert api_client.get("/items?domain=bogus").status_code == 422


def test_filter_by_single_tag(api_client, sqlite_factory):
    _seed(sqlite_factory)
    data = api_client.get("/items?tag=redis").json()
    assert {i["slug"] for i in data} == {"be-1", "be-2"}


def test_multiple_tags_are_anded(api_client, sqlite_factory):
    _seed(sqlite_factory)
    data = api_client.get("/items?tag=redis&tag=cache").json()
    assert {i["slug"] for i in data} == {"be-1"}


def test_domain_and_tag_compose(api_client, sqlite_factory):
    _seed(sqlite_factory)
    data = api_client.get("/items?domain=backend&tag=cache").json()
    assert {i["slug"] for i in data} == {"be-1"}


def test_summary_exposes_domain_and_tags(api_client, sqlite_factory):
    _seed(sqlite_factory)
    be1 = next(i for i in api_client.get("/items").json() if i["slug"] == "be-1")
    assert be1["domain"] == "backend"
    assert set(be1["tags"]) == {"redis", "cache"}
