from k7e_api.models import (
    Base,
    KnowledgeItem,
    KnowledgeItemVersion,
    WikiChunk,
)
from sqlalchemy import StaticPool, create_engine, select
from sqlalchemy.orm import Session, sessionmaker


def test_wiki_chunk_roundtrip():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False, class_=Session)
    with factory() as s:
        item = KnowledgeItem(slug="s", title="T", status="published")
        s.add(item)
        s.flush()
        ver = KnowledgeItemVersion(
            item_id=item.id, markdown_body="b", model_id="m", created_by="w"
        )
        s.add(ver)
        s.flush()
        s.add(
            WikiChunk(
                item_id=item.id,
                version_id=ver.id,
                chunk_index=0,
                chunk_text="hello",
                embedding=[0.1, 0.2, 0.3],
            )
        )
        s.commit()
        got = s.execute(select(WikiChunk)).scalar_one()
        assert got.embedding == [0.1, 0.2, 0.3]
        assert ver.chunks[0].id == got.id
    Base.metadata.drop_all(engine)
