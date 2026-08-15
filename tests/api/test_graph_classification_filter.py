"""M4: GET /graph ?domain= filters nodes (and dangling edges follow)."""

from __future__ import annotations

from datetime import datetime, timezone

from k7e_api.models import KnowledgeItem, KnowledgeItemVersion, WikiLink


def _now():
    return datetime.now(timezone.utc)


def _publish(session, slug, domain):
    item = KnowledgeItem(
        slug=slug,
        title=slug,
        status="published",
        domain=domain,
        created_at=_now(),
        updated_at=_now(),
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
        created_at=_now(),
    )
    session.add(ver)
    session.flush()
    item.current_version_id = ver.id
    return item


def test_graph_domain_filters_nodes_and_edges(api_client, sqlite_factory):
    with sqlite_factory() as s:
        a = _publish(s, "be-a", "backend")
        b = _publish(s, "be-b", "backend")
        c = _publish(s, "fe-c", "frontend")
        for src, tgt in ((a, b), (b, a), (a, c), (c, a)):
            s.add(
                WikiLink(
                    source_item_id=src.id,
                    target_item_id=tgt.id,
                    relation="related",
                    score=1.0,
                    origin="explicit",
                )
            )
        s.commit()

    data = api_client.get("/graph?domain=backend").json()
    assert {n["slug"] for n in data["nodes"]} == {"be-a", "be-b"}
    # the a<->c edge is dropped because c is filtered out
    assert len(data["edges"]) == 1
