"""Embedding client seam: LiteLLM-backed production client + deterministic stub."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol, runtime_checkable

import litellm

from k7e_api.config import get_settings

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@runtime_checkable
class EmbeddingClient(Protocol):
    """Contract for embedding backends."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text, in order."""
        ...


class LiteLLMEmbeddingClient:
    """Production embedding client: routes through LiteLLM to the gateway."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        settings = get_settings()
        # Model names are logical LiteLLM aliases; a bare alias must be prefixed
        # with ``openai/`` so the SDK routes it through the gateway (matches
        # ``LiteLLMClient.complete_json``). Without this, litellm.aembedding
        # raises "LLM Provider NOT provided. You passed model=wiki-embed".
        model = settings.wiki_embed_model
        if "/" not in model:
            model = f"openai/{model}"
        response = await litellm.aembedding(
            model=model,
            input=texts,
            api_base=settings.litellm_base_url,
            api_key=settings.litellm_api_key,
            num_retries=settings.llm_num_retries,
            timeout=settings.embed_timeout_seconds,
        )
        return [item["embedding"] for item in response.data]


class StubEmbeddingClient:
    """Deterministic hashing vectorizer for tests (token overlap -> cosine).

    NOT semantic — it models lexical overlap only, which is enough to make
    hybrid-ranking tests deterministic.
    """

    def __init__(self, dim: int = 256) -> None:
        self._dim = dim

    def _vec(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        for tok in _TOKEN_RE.findall(text.lower()):
            idx = int(hashlib.md5(tok.encode()).hexdigest(), 16) % self._dim
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]
