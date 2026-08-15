"""Scheduled embedding backfill: fill WikiChunk rows the mirror left NULL.

Bounded (``embed_backfill_batch_size`` per run), resumable (a gateway 429 leaves
rows NULL for the next run), fail-fast — persistence never depends on it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from k7e_api.config import get_settings
from k7e_api.db import SessionLocal
from k7e_api.logging_setup import get_logger
from k7e_api.models import WikiChunk
from sqlalchemy import func, select
from temporalio import activity

session_factory: Callable = SessionLocal
logger = get_logger(__name__)


def _default_embedding_client():
    import os

    impl = os.environ.get("EMBEDDING_CLIENT_IMPL", "litellm").lower()
    if impl == "stub":
        from k7e_api.embedding_client import StubEmbeddingClient

        return StubEmbeddingClient()
    from k7e_api.embedding_client import LiteLLMEmbeddingClient

    return LiteLLMEmbeddingClient()


embedding_client_factory: Callable = _default_embedding_client


@dataclass
class _Cfg:  # test seam only; production uses the real Settings
    batch: int
    enabled: bool

    @property
    def embed_backfill_batch_size(self) -> int:
        return self.batch

    @property
    def embeddings_enabled(self) -> bool:
        return self.enabled


def _remaining(session) -> int:
    return session.execute(
        select(func.count()).select_from(WikiChunk).where(WikiChunk.embedding.is_(None))
    ).scalar_one()


@activity.defn
async def embed_backfill_activity() -> dict:
    """Embed up to one batch of NULL-embedding chunks. Returns {embedded, remaining}."""
    settings = get_settings()
    if not settings.embeddings_enabled:
        return {"embedded": 0, "remaining": 0, "skipped": "disabled"}

    with session_factory() as session:
        rows = (
            session.execute(
                select(WikiChunk)
                .where(WikiChunk.embedding.is_(None))
                .order_by(WikiChunk.created_at, WikiChunk.id)
                .limit(settings.embed_backfill_batch_size)
            )
            .scalars()
            .all()
        )
        if not rows:
            return {"embedded": 0, "remaining": 0}

        client = embedding_client_factory()
        try:
            vectors = await client.embed([r.chunk_text for r in rows])
        except Exception as exc:  # noqa: BLE001 - fail-fast, retry next run
            logger.warning("embed_backfill_failed", count=len(rows), error=str(exc))
            return {"embedded": 0, "remaining": _remaining(session)}

        for row, vec in zip(rows, vectors):
            row.embedding = vec
        session.commit()
        remaining = _remaining(session)

    logger.info("embed_backfill", embedded=len(rows), remaining=remaining)
    return {"embedded": len(rows), "remaining": remaining}
