from types import SimpleNamespace

from k7e_api import config, embedding_client
from k7e_api.embedding_client import StubEmbeddingClient


async def test_stub_is_deterministic_and_overlap_scores_higher():
    stub = StubEmbeddingClient()
    (a1,) = await stub.embed(["payment service incident"])
    (a2,) = await stub.embed(["payment service incident"])
    assert a1 == a2  # deterministic
    overlap, disjoint = await stub.embed(["payment service", "zzz qqq"])

    def cos(u, v):
        import math

        dot = sum(x * y for x, y in zip(u, v))
        nu = math.sqrt(sum(x * x for x in u)) or 1.0
        nv = math.sqrt(sum(x * x for x in v)) or 1.0
        return dot / (nu * nv)

    assert cos(a1, overlap) > cos(a1, disjoint)


async def test_litellm_embedding_passes_model_and_kwargs(monkeypatch):
    config.get_settings.cache_clear()
    monkeypatch.setenv("WIKI_EMBED_MODEL", "wiki-embed")
    monkeypatch.setenv("EMBED_TIMEOUT_SECONDS", "11")
    monkeypatch.setenv("LLM_NUM_RETRIES", "3")
    captured = {}

    async def fake_aembedding(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(data=[{"embedding": [0.1, 0.2]}])

    monkeypatch.setattr(embedding_client.litellm, "aembedding", fake_aembedding)
    out = await embedding_client.LiteLLMEmbeddingClient().embed(["hello"])
    assert out == [[0.1, 0.2]]
    # A bare alias must be routed through the gateway via the openai/ prefix,
    # otherwise litellm raises "LLM Provider NOT provided".
    assert captured["model"] == "openai/wiki-embed"
    assert captured["timeout"] == 11.0
    assert captured["num_retries"] == 3
    config.get_settings.cache_clear()


async def test_litellm_embedding_preserves_explicit_provider_prefix(monkeypatch):
    """An alias that already carries a provider prefix is passed through as-is."""
    config.get_settings.cache_clear()
    monkeypatch.setenv("WIKI_EMBED_MODEL", "azure/my-embed")
    captured = {}

    async def fake_aembedding(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(data=[{"embedding": [0.0]}])

    monkeypatch.setattr(embedding_client.litellm, "aembedding", fake_aembedding)
    await embedding_client.LiteLLMEmbeddingClient().embed(["hi"])
    assert captured["model"] == "azure/my-embed"
    config.get_settings.cache_clear()
