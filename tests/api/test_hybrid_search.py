from k7e_api.embedding_client import StubEmbeddingClient
from k7e_api.models import Base, KnowledgeItem, KnowledgeItemVersion, WikiChunk
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


async def _seed(factory, slug, title, body):
    stub = StubEmbeddingClient()
    with factory() as s:
        item = KnowledgeItem(slug=slug, title=title, status="published")
        s.add(item)
        s.flush()
        ver = KnowledgeItemVersion(
            item_id=item.id, markdown_body=body, model_id="m", created_by="w"
        )
        s.add(ver)
        s.flush()
        item.current_version_id = ver.id
        (vec,) = await stub.embed([body])
        s.add(
            WikiChunk(
                item_id=item.id,
                version_id=ver.id,
                chunk_index=0,
                chunk_text=body,
                embedding=vec,
            )
        )
        s.commit()


async def test_unknown_query_returns_empty():
    factory = _factory()
    await _seed(factory, "p", "Payment Service", "payment service handles billing")
    (qvec,) = await StubEmbeddingClient().embed(["zzz nonexistent term"])
    with factory() as s:
        hits = HybridSearchProvider().query(
            text="zzz nonexistent term",
            query_embedding=qvec,
            allowed_ids=None,
            limit=20,
            session=s,
        )
    assert hits == []


async def test_vector_overlap_returns_hit_without_exact_title():
    factory = _factory()
    await _seed(factory, "p", "Payment Service", "payment billing invoices charges")
    (qvec,) = await StubEmbeddingClient().embed(["billing invoices"])
    with factory() as s:
        hits = HybridSearchProvider().query(
            text="billing invoices",
            query_embedding=qvec,
            allowed_ids=None,
            limit=20,
            session=s,
        )
    assert [h.slug for h in hits] == ["p"]
    assert hits[0].score > 0


def test_keyword_score_matches_cjk_terms():
    """Keyword scoring must work for Japanese (no spaces) — vital in keyword-only
    mode. The ASCII-only tokenizer used to score every CJK query as 0.0."""
    from k7e_api.search import _keyword_score

    # ASCII behaviour is unchanged.
    assert _keyword_score("example bank", "Example Bank Super Loan") == 1.0
    # Exact Japanese term matches its page.
    assert _keyword_score("Example Bank", "Example Bank (Example Bank) loan review") == 1.0
    # A shorter Japanese substring still matches via character bigrams.
    assert _keyword_score("審査", "Example Bank ローン審査") > 0.0
    # Unrelated Japanese query does not match.
    assert _keyword_score("味噌汁", "Example Bank loan") == 0.0
