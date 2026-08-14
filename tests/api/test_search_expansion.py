from k7e_api.embedding_client import StubEmbeddingClient
from k7e_api.models import Base, KnowledgeItem, KnowledgeItemVersion, WikiLink
from k7e_api.search import HybridSearchProvider
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker


def _factory():
    e = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(e)
    return sessionmaker(e, expire_on_commit=False, class_=Session)


def _add(s, slug, body):
    item = KnowledgeItem(slug=slug, title=slug, status="published")
    s.add(item)
    s.flush()
    ver = KnowledgeItemVersion(item_id=item.id, markdown_body=body, model_id="m", created_by="w")
    s.add(ver)
    s.flush()
    item.current_version_id = ver.id
    return item.id


async def test_expansion_surfaces_neighbor_of_a_hit(monkeypatch):
    factory = _factory()
    with factory() as s:
        a = _add(s, "alpha-page", "alpha alpha alpha")  # matches query "alpha"
        b = _add(s, "beta-page", "beta beta beta")  # does NOT match "alpha"
        s.add(
            WikiLink(
                source_item_id=a,
                target_item_id=b,
                relation="related",
                score=0.9,
                origin="vector",
            )
        )
        s.commit()
        (qvec,) = await StubEmbeddingClient().embed(["alpha"])
        hits = HybridSearchProvider().query(
            text="alpha", query_embedding=qvec, allowed_ids=None, limit=10, session=s
        )
    slugs = [h.slug for h in hits]
    assert "alpha-page" in slugs and "beta-page" in slugs  # neighbor surfaced via expansion
    assert slugs.index("alpha-page") < slugs.index(
        "beta-page"
    )  # neighbor ranks below the hit (decayed)


async def test_expansion_handles_multiple_top_hits_with_distinct_neighbors():
    """Two direct hits each with a different neighbor — both neighbors surfaced."""
    factory = _factory()
    with factory() as s:
        # Two direct hits for "alpha beta"
        a = _add(s, "alpha-page", "alpha beta gamma delta")
        b = _add(s, "beta-page", "alpha beta epsilon zeta")
        # Two neighbors — neither matches the query directly
        na = _add(s, "neighbor-of-a", "unrelated content here zzz")
        nb = _add(s, "neighbor-of-b", "different unrelated content yyy")
        s.add(
            WikiLink(
                source_item_id=a,
                target_item_id=na,
                relation="related",
                score=0.8,
                origin="vector",
            )
        )
        s.add(
            WikiLink(
                source_item_id=b,
                target_item_id=nb,
                relation="related",
                score=0.7,
                origin="vector",
            )
        )
        s.commit()
        (qvec,) = await StubEmbeddingClient().embed(["alpha beta"])
        hits = HybridSearchProvider().query(
            text="alpha beta",
            query_embedding=qvec,
            allowed_ids=None,
            limit=10,
            session=s,
        )
    slugs = [h.slug for h in hits]
    # Both direct hits must appear
    assert "alpha-page" in slugs, f"alpha-page missing from {slugs}"
    assert "beta-page" in slugs, f"beta-page missing from {slugs}"
    # Both neighbors must be surfaced via 1-hop expansion
    assert "neighbor-of-a" in slugs, f"neighbor-of-a not expanded into {slugs}"
    assert "neighbor-of-b" in slugs, f"neighbor-of-b not expanded into {slugs}"
    # Direct hits rank above their respective expanded neighbors (expansion decay)
    assert slugs.index("alpha-page") < slugs.index("neighbor-of-a")
    assert slugs.index("beta-page") < slugs.index("neighbor-of-b")
