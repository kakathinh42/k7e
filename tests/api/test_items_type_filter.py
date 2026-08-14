"""GET /items ?type= filter + ItemSummary.type field."""

from __future__ import annotations

from k7e_api.models import KnowledgeItem, KnowledgeItemVersion


def _publish(session, slug: str, title: str, item_type: str) -> None:
    """Seed one published KnowledgeItem of the given type with a current version."""
    item = KnowledgeItem(slug=slug, title=title, status="published", type=item_type)
    session.add(item)
    session.flush()
    ver = KnowledgeItemVersion(
        item_id=item.id,
        version_number=1,
        markdown_body=f"# {title}\n\nbody",
        model_id="test",
        created_by="test",
        citations=[],
        status="published",
        title=title,
    )
    session.add(ver)
    session.flush()
    item.current_version_id = ver.id


def _seed(sqlite_factory):
    with sqlite_factory() as s:
        _publish(s, "src-a", "Source A", "source")
        _publish(s, "src-b", "Source B", "source")
        _publish(s, "ent-a", "Entity A", "entity")
        _publish(s, "con-a", "Concept A", "concept")
        _publish(s, "ana-a", "Analysis A", "analysis")
        s.commit()


def test_items_no_param_returns_all_types(api_client, sqlite_factory):
    _seed(sqlite_factory)
    data = api_client.get("/items").json()
    assert {i["slug"] for i in data} == {"src-a", "src-b", "ent-a", "con-a", "ana-a"}


def test_items_filter_source_returns_only_sources(api_client, sqlite_factory):
    _seed(sqlite_factory)
    data = api_client.get("/items?type=source").json()
    assert {i["slug"] for i in data} == {"src-a", "src-b"}
    assert all(i["type"] == "source" for i in data)


def test_items_filter_concept_returns_only_concepts(api_client, sqlite_factory):
    _seed(sqlite_factory)
    data = api_client.get("/items?type=concept").json()
    assert {i["slug"] for i in data} == {"con-a"}
    assert all(i["type"] == "concept" for i in data)


def test_items_summary_includes_type_field(api_client, sqlite_factory):
    _seed(sqlite_factory)
    data = api_client.get("/items").json()
    assert data and all("type" in i for i in data)


def test_items_filter_rejects_unknown_type(api_client, sqlite_factory):
    _seed(sqlite_factory)
    resp = api_client.get("/items?type=bogus")
    assert resp.status_code == 422, resp.text


def test_items_filter_analysis_returns_only_analysis(api_client, sqlite_factory):
    _seed(sqlite_factory)
    data = api_client.get("/items?type=analysis").json()
    assert {i["slug"] for i in data} == {"ana-a"}
    assert all(i["type"] == "analysis" for i in data)
