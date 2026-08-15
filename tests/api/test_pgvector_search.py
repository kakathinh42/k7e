"""Postgres-only parity: _vector_similarity_map matches the Python cosine path.

Skipped unless WIKI_TEST_PG_DSN points at a pgvector-enabled Postgres
(developer-run; not CI). Example:
    WIKI_TEST_PG_DSN=postgresql+psycopg://wiki:wiki@localhost:5435/wiki \
        .venv/bin/python -m pytest tests/api/test_pgvector_search.py -v
"""

from __future__ import annotations

import os

import pytest
from k7e_api.graph import cosine
from k7e_api.models import Base, KnowledgeItem, KnowledgeItemVersion, Organization, WikiChunk
from k7e_api.search import _vector_similarity_map
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

_DSN = os.environ.get("WIKI_TEST_PG_DSN")
pytestmark = pytest.mark.skipif(not _DSN, reason="WIKI_TEST_PG_DSN not set")


def _vec(seed: float) -> list[float]:
    # A deterministic 1536-dim vector.
    return [seed] + [0.0] * 1535


def test_vector_similarity_map_matches_python_cosine():
    engine = create_engine(_DSN)
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as s:
            org = Organization(slug="pgvec-test", name="pgvec-test")
            s.add(org)
            s.flush()
            item = KnowledgeItem(
                org_id=org.id, slug="p", title="P", status="published", type="source"
            )
            s.add(item)
            s.flush()
            v1 = KnowledgeItemVersion(
                item_id=item.id,
                version_number=1,
                markdown_body="a",
                model_id="t",
                created_by="t",
                citations=[],
                status="published",
                title="P",
            )
            v2 = KnowledgeItemVersion(
                item_id=item.id,
                version_number=2,
                markdown_body="b",
                model_id="t",
                created_by="t",
                citations=[],
                status="published",
                title="P",
            )
            s.add_all([v1, v2])
            s.flush()
            s.add(
                WikiChunk(
                    item_id=item.id,
                    version_id=v1.id,
                    chunk_index=0,
                    chunk_text="a",
                    embedding=_vec(1.0),
                )
            )
            s.add(
                WikiChunk(
                    item_id=item.id,
                    version_id=v2.id,
                    chunk_index=0,
                    chunk_text="b",
                    embedding=_vec(-1.0),
                )
            )
            s.commit()

            q = _vec(1.0)
            vmap = _vector_similarity_map(s, q, [v1.id, v2.id])
            assert vmap is not None and set(vmap) == {v1.id, v2.id}
            assert vmap[v1.id] > vmap[v2.id]
            assert vmap[v1.id] == pytest.approx(cosine(q, _vec(1.0)), abs=1e-4)
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
