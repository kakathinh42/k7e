"""EmbeddingVector normalizes to list[float] and round-trips on SQLite (JSON path)."""

from __future__ import annotations

from k7e_api.embedding_type import EMBEDDING_DIM, EmbeddingVector
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, insert, select


def test_embedding_dim_is_1536():
    assert EMBEDDING_DIM == 1536


def test_bind_normalizes_to_list_of_float():
    col = EmbeddingVector()
    assert col.process_bind_param([1, 2, 3], None) == [1.0, 2.0, 3.0]
    assert col.process_bind_param((4, 5), None) == [4.0, 5.0]
    assert col.process_bind_param(None, None) is None


def test_result_normalizes_to_list_of_float():
    col = EmbeddingVector()
    assert col.process_result_value([1, 2, 3], None) == [1.0, 2.0, 3.0]
    assert col.process_result_value(None, None) is None


def test_round_trips_through_sqlite_json():
    engine = create_engine("sqlite:///:memory:")
    md = MetaData()
    t = Table("t", md, Column("id", Integer, primary_key=True), Column("e", EmbeddingVector()))
    md.create_all(engine)
    with engine.begin() as conn:
        conn.execute(insert(t).values(id=1, e=[0.1, 0.2, 0.3]))
        got = conn.execute(select(t.c.e).where(t.c.id == 1)).scalar_one()
    assert got == [0.1, 0.2, 0.3]
