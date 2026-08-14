from k7e_api.models import Base, KnowledgeItem, WikiLink
from sqlalchemy import StaticPool, create_engine, select
from sqlalchemy.orm import Session, sessionmaker


def test_wiki_link_roundtrip():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False, class_=Session)
    with factory() as s:
        a = KnowledgeItem(slug="a", title="A", status="published")
        b = KnowledgeItem(slug="b", title="B", status="published")
        s.add_all([a, b])
        s.flush()
        s.add(
            WikiLink(
                source_item_id=a.id,
                target_item_id=b.id,
                relation="related",
                score=0.8,
                origin="vector",
            )
        )
        s.commit()
        got = s.execute(select(WikiLink)).scalar_one()
        assert got.source_item_id == a.id and got.target_item_id == b.id
        assert got.relation == "related" and got.origin == "vector" and got.score == 0.8
    Base.metadata.drop_all(engine)
