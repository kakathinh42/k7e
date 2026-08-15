"""Regenerate tests/fixtures/eval/vectors.json from the frozen corpus + labels.

Embeds every corpus chunk (chunked with the production chunk_markdown) and every
label query via the real gateway. Run when the corpus, labels, or embedding model
changes. Requires the LiteLLM proxy reachable (LITELLM_BASE_URL/LITELLM_API_KEY).

Usage:  python scripts/search_bench_refresh.py
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import yaml

from k7e_api.chunking import chunk_markdown
from k7e_api.config import get_settings
from k7e_api.embedding_client import LiteLLMEmbeddingClient

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "eval"


async def main() -> None:
    manifest = yaml.safe_load((FIXTURES / "corpus" / "manifest.yaml").read_text())
    labels = yaml.safe_load((FIXTURES / "labels.yaml").read_text())

    client = LiteLLMEmbeddingClient()  # reads model/timeout from settings

    chunk_vectors: dict[str, list[list[float]]] = {}
    for entry in manifest:
        body = (FIXTURES / "corpus" / entry["file"]).read_text()
        chunks = chunk_markdown(body)
        chunk_vectors[entry["slug"]] = await client.embed(chunks)

    queries = list(labels.keys())
    query_vecs = await client.embed(queries)
    query_vectors = dict(zip(queries, query_vecs))

    out = {
        "model": get_settings().wiki_embed_model,
        "chunks": chunk_vectors,
        "queries": query_vectors,
    }
    (FIXTURES / "vectors.json").write_text(json.dumps(out))
    print(
        f"wrote {FIXTURES / 'vectors.json'}: "
        f"{len(chunk_vectors)} pages, {len(query_vectors)} queries"
    )


if __name__ == "__main__":
    asyncio.run(main())
