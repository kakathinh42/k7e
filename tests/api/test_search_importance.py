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


def _add_item(s, slug, body):
    item = KnowledgeItem(slug=slug, title=f"{slug} alpha", status="published")
    s.add(item)
    s.flush()
    ver = KnowledgeItemVersion(item_id=item.id, markdown_body=body, model_id="m", created_by="w")
    s.add(ver)
    s.flush()
    item.current_version_id = ver.id
    return item.id


async def test_higher_degree_ranks_higher(monkeypatch):
    monkeypatch.setenv("SEARCH_W_IMPORTANCE", "1.0")  # exaggerate so the effect is visible
    from k7e_api import config

    config.get_settings.cache_clear()
    factory = _factory()
    with factory() as s:
        _add_item(s, "a", "alpha topic")
        b = _add_item(s, "b", "alpha topic")
        other = _add_item(s, "c", "alpha topic")
        # give B two inbound edges (degree 2), A none
        s.add(
            WikiLink(
                source_item_id=other,
                target_item_id=b,
                relation="related",
                score=0.9,
                origin="vector",
            )
        )
        s.add(
            WikiLink(
                source_item_id=b,
                target_item_id=other,
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
    order = [h.slug for h in hits]
    assert order.index("b") < order.index("a")  # higher-degree B outranks A
    config.get_settings.cache_clear()
