"""Dialect-aware embedding column type.

On PostgreSQL the embedding is stored as a real pgvector ``vector(N)`` column
(so it can be ANN-indexed and compared with the ``<=>`` operator). On any other
dialect — notably the in-memory SQLite used by the test suite — it falls back to
JSON. Either way Python sees a plain ``list[float]``, so callers (graph
centroids, dedup, search) are dialect-agnostic.

The dimension is fixed (``EMBEDDING_DIM``) because pgvector ANN indexes require a
known dimension. It must match the embedding model in
``deploy/litellm/litellm_config.yaml`` (text-embedding-3-small -> 1536).
"""

from __future__ import annotations

from sqlalchemy import JSON
from sqlalchemy.types import TypeDecorator

#: Dimensions of the configured embedding model (text-embedding-3-small).
EMBEDDING_DIM = 1536

try:  # pgvector is only needed for the PostgreSQL path
    from pgvector.sqlalchemy import Vector

    _HAS_PGVECTOR = True
except ImportError:  # pragma: no cover - exercised only without the dep
    Vector = None  # type: ignore[assignment]
    _HAS_PGVECTOR = False


class EmbeddingVector(TypeDecorator):
    """``vector(dim)`` on PostgreSQL, ``JSON`` elsewhere; always list[float] in Python."""

    impl = JSON
    cache_ok = True

    def __init__(self, dim: int = EMBEDDING_DIM, **kwargs):
        self.dim = dim
        super().__init__(**kwargs)

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql" and _HAS_PGVECTOR:
            return dialect.type_descriptor(Vector(self.dim))
        # ``none_as_null=True`` binds Python ``None`` to SQL NULL rather than the
        # JSON literal ``'null'``. This makes the JSON fallback (SQLite tests)
        # model the pgvector column faithfully: a text-first chunk written with
        # ``embedding=None`` is a real SQL NULL, so the backfill's
        # ``WHERE embedding IS NULL`` poll matches it on every dialect.
        return dialect.type_descriptor(JSON(none_as_null=True))

    def process_bind_param(self, value, dialect):
        # Accept list / tuple / numpy array uniformly; store as a plain sequence.
        return None if value is None else [float(x) for x in value]

    def process_result_value(self, value, dialect):
        # pgvector returns an ndarray, JSON returns a list - normalise to list[float].
        return None if value is None else [float(x) for x in value]
