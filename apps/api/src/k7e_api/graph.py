"""Pure vector-graph helpers: page centroids + nearest-neighbour selection.

Used by the link-build activity to derive page<->page similarity edges from
chunk embeddings. No DB or framework dependencies — trivially unit-testable.
"""

from __future__ import annotations

import math
import uuid


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two equal-length vectors (0.0 if either is empty)."""
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


def page_centroid(chunk_embeddings: list[list[float]]) -> list[float]:
    """L2-normalised mean of a page's chunk embeddings ([] when none)."""
    if not chunk_embeddings:
        return []
    dim = len(chunk_embeddings[0])
    acc = [0.0] * dim
    for vec in chunk_embeddings:
        for i, x in enumerate(vec):
            acc[i] += x
    n = len(chunk_embeddings)
    mean = [x / n for x in acc]
    norm = math.sqrt(sum(x * x for x in mean)) or 1.0
    return [x / norm for x in mean]


def top_k_neighbors(
    target: list[float],
    candidates: list[tuple[uuid.UUID, list[float]]],
    k: int,
    min_sim: float,
) -> list[tuple[uuid.UUID, float]]:
    """Return up to k (item_id, score) with cosine >= min_sim, score-descending."""
    scored = [(item_id, cosine(target, c)) for item_id, c in candidates if c]
    scored = [(i, s) for i, s in scored if s >= min_sim]
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored[:k]
