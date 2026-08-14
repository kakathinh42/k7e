"""M4: GET /facets — permission-scoped domain/tag/type counts."""

from __future__ import annotations

import uuid

from k7e_api.models import ItemTag, KnowledgeItem, KnowledgeItemVersion


def _publish(session, slug, *, domain, type_="source", tags=(), org_id=None):
    item = KnowledgeItem(
        slug=slug,
        title=slug,
        status="published",
        type=type_,
        domain=domain,
        org_id=org_id,
    )
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
        session.add(ItemTag(item_id=item.id, tag=tag, org_id=org_id))


def test_facets_counts(api_client, sqlite_factory):
    with sqlite_factory() as s:
        _publish(s, "a", domain="backend", type_="source", tags=["redis"])
        _publish(s, "b", domain="backend", type_="concept", tags=["redis", "cache"])
        _publish(s, "c", domain="frontend", type_="source", tags=["react"])
        s.commit()

    data = api_client.get("/facets").json()
    domains = {d["value"]: d["count"] for d in data["domains"]}
    assert domains == {"backend": 2, "frontend": 1}
    tags = {t["value"]: t["count"] for t in data["tags"]}
    assert tags == {"redis": 2, "cache": 1, "react": 1}
    types = {t["value"]: t["count"] for t in data["types"]}
    assert types == {"source": 2, "concept": 1}


def test_facets_exclude_other_org(api_client, sqlite_factory):
    # api_client is fixed to TEST_TENANT_CONTEXT (org ...0001). A page seeded at
    # a different explicit org must not appear in the counts (scoped()).
    other_org = uuid.UUID("00000000-0000-0000-0000-0000000000ff")
    with sqlite_factory() as s:
        _publish(s, "mine", domain="backend", tags=["redis"])
        _publish(s, "theirs", domain="security", tags=["secret"], org_id=other_org)
        s.commit()

    data = api_client.get("/facets").json()
    assert {d["value"] for d in data["domains"]} == {"backend"}
    assert "secret" not in {t["value"] for t in data["tags"]}
