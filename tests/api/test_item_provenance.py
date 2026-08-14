"""GET /items/{slug} resolves KnowledgeItem.provenance into ItemDetail.sources."""

from __future__ import annotations

from k7e_api.models import KnowledgeItem, KnowledgeItemVersion, RawDocument


def _publish(session, slug, title, item_type, provenance):
    item = KnowledgeItem(
        slug=slug,
        title=title,
        status="published",
        type=item_type,
        provenance=provenance,
    )
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
    return item


def test_source_page_resolves_document(api_client, sqlite_factory):
    sha = "s" * 64
    with sqlite_factory() as s:
        s.add(
            RawDocument(
                filename="api-spec.md",
                sha256=sha,
                object_store_ref="raw/manual/api-spec.md",
                mime_type="text/markdown",
                source_system="manual_upload",
            )
        )
        _publish(
            s,
            "api-rate-limiting",
            "API Rate Limiting",
            "source",
            {"resource": sha, "source_pages": []},
        )
        s.commit()

    data = api_client.get("/items/api-rate-limiting").json()
    assert len(data["sources"]) == 1
    d = data["sources"][0]
    assert d["kind"] == "document"
    assert d["label"] == "api-spec.md"
    assert d["source_system"] == "manual_upload"
    assert d["raw_document_id"]  # present + non-null


def test_derived_page_resolves_source_pages(api_client, sqlite_factory):
    with sqlite_factory() as s:
        _publish(
            s,
            "api-rate-limiting",
            "API Rate Limiting",
            "source",
            {"resource": "x", "source_pages": []},
        )
        _publish(
            s,
            "token-bucket",
            "Token Bucket",
            "concept",
            {"resource": None, "source_pages": ["api-rate-limiting"]},
        )
        s.commit()

    data = api_client.get("/items/token-bucket").json()
    assert data["sources"] == [
        {"kind": "page", "slug": "api-rate-limiting", "title": "API Rate Limiting"}
    ]


def test_unmatched_resource_degrades_to_label(api_client, sqlite_factory):
    with sqlite_factory() as s:
        _publish(
            s,
            "ext",
            "Ext",
            "source",
            {"resource": "https://confluence/x", "source_pages": []},
        )
        s.commit()

    data = api_client.get("/items/ext").json()
    assert data["sources"] == [
        {
            "kind": "document",
            "raw_document_id": None,
            "label": "https://confluence/x",
            "source_system": None,
        }
    ]


def test_null_provenance_yields_empty_sources(api_client, sqlite_factory):
    with sqlite_factory() as s:
        _publish(s, "bare", "Bare", "source", None)
        s.commit()

    data = api_client.get("/items/bare").json()
    assert data["sources"] == []
