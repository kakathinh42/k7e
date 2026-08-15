"""Reusable retrieval-eval core: fixtures → SQLite seed → real provider → metrics.

Kept out of the shipped k7e_api package. Imported as a sibling by
tests/api/test_search_bench.py and via sys.path by scripts/search_bench.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from k7e_api.chunking import chunk_markdown
from k7e_api.models import Base, KnowledgeItem, KnowledgeItemVersion, WikiChunk
from k7e_api.search import HybridSearchProvider
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "eval"


def recall_at_k(per_query: list[dict], k: int) -> float:
    """Mean over queries of |expected ∩ top-k| / |expected|."""
    if not per_query:
        return 0.0
    total = 0.0
    for r in per_query:
        expected = set(r["expected"])
        if not expected:
            continue
        topk = set(r["ranked"][:k])
        total += len(expected & topk) / len(expected)
    return total / len(per_query)


def mrr(per_query: list[dict], k: int = 10) -> float:
    """Mean reciprocal rank of the first expected slug within the top-k."""
    if not per_query:
        return 0.0
    total = 0.0
    for r in per_query:
        expected = set(r["expected"])
        for idx, slug in enumerate(r["ranked"][:k], start=1):
            if slug in expected:
                total += 1.0 / idx
                break
    return total / len(per_query)


def make_session() -> Session:
    """A Session on a fresh in-memory SQLite DB (uses the in-Python cosine path).

    Single-use: the caller owns no teardown obligation — this is a StaticPool
    in-memory session the process reclaims on exit. Deliberately NOT the
    ``sqlite_factory`` conftest fixture, which the harness can't use because it
    must also run outside pytest (the Task 5 CLI).
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False, class_=Session)()


def seed_corpus(session: Session, corpus: dict, vectors: dict) -> None:
    """Insert each page as a published item + version + chunks with cached vectors."""
    for slug, page in corpus.items():
        item = KnowledgeItem(slug=slug, type="concept", title=page["title"], status="published")
        session.add(item)
        session.flush()
        version = KnowledgeItemVersion(
            item_id=item.id,
            version_number=1,
            markdown_body=page["body"],
            model_id="eval",
            created_by="eval",
            status="published",
            title=page["title"],
            citations=[],
        )
        session.add(version)
        session.flush()
        item.current_version_id = version.id  # search joins on the current version
        chunk_vecs = vectors["chunks"][slug]
        chunks = chunk_markdown(page["body"])
        if len(chunks) != len(chunk_vecs):
            raise RuntimeError(
                f"stale vectors.json for {slug!r}: {len(chunks)} chunks "
                f"vs {len(chunk_vecs)} cached vectors — re-run search_bench_refresh.py"
            )
        for i, text in enumerate(chunks):
            session.add(
                WikiChunk(
                    item_id=item.id,
                    version_id=version.id,
                    chunk_index=i,
                    chunk_text=text,
                    embedding=chunk_vecs[i],
                )
            )
    session.commit()


def run_eval(
    session: Session, labels: dict, vectors: dict, ks: tuple[int, ...] = (5, 10)
) -> list[dict]:
    """Run the real provider per labeled query; return per-query ranked slugs."""
    provider = HybridSearchProvider()
    limit = max(ks)
    per_query: list[dict] = []
    for query, expected in labels.items():
        query_embedding = vectors["queries"][query]
        # ctx=None + allowed_ids=None on purpose: the eval measures ranking, not
        # permissions. This also makes the harness entry-point-independent — the
        # pytest-only before_flush RBAC hook (tests/api/conftest.py) that stamps
        # org_id on this session is inert here because no org/permission predicate
        # is applied, so CLI-measured and pytest-gate-measured recall are identical.
        hits = provider.query(query, query_embedding, None, limit, session)
        per_query.append({"query": query, "expected": expected, "ranked": [h.slug for h in hits]})
    return per_query


def load_fixtures(fixtures_dir: Path = _FIXTURES_DIR) -> tuple[dict, dict, dict]:
    """Return (corpus, labels, vectors) from the frozen fixture directory.

    Fails loudly if the cached vectors were produced under a different embedding
    model than the runtime resolves: model-mismatched vectors would silently
    corrupt the recall baseline. Inert in CI, where the default ``wiki-embed``
    alias matches what ``search_bench_refresh.py`` records.
    """
    from k7e_api.config import get_settings

    manifest = yaml.safe_load((fixtures_dir / "corpus" / "manifest.yaml").read_text())
    labels = yaml.safe_load((fixtures_dir / "labels.yaml").read_text())
    vectors = json.loads((fixtures_dir / "vectors.json").read_text())
    runtime_model = get_settings().wiki_embed_model
    if vectors.get("model") != runtime_model:
        raise RuntimeError(
            f"vectors.json was built for embedding model {vectors.get('model')!r} "
            f"but the runtime uses {runtime_model!r} — re-run search_bench_refresh.py"
        )
    corpus = {
        entry["slug"]: {
            "title": entry["title"],
            "body": (fixtures_dir / "corpus" / entry["file"]).read_text(),
        }
        for entry in manifest
    }
    return corpus, labels, vectors
