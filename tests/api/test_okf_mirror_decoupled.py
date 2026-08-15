"""After decoupling, the mirror writes chunk text with embedding=NULL and never embeds."""

from __future__ import annotations

from k7e_api.models import WikiChunk
from k7e_api.okf import OkfFrontmatter, OkfPage
from k7e_api.okf_bundle import OkfBundle
from k7e_api.okf_mirror import mirror_bundle
from sqlalchemy import select


def _one_page_bundle(tmp_path):
    """Build a one-page OKF bundle the same way tests/api/test_okf_mirror.py does."""
    bundle = OkfBundle(tmp_path)
    bundle.init()
    bundle.write_page(
        OkfPage(
            slug="hot-cache",
            frontmatter=OkfFrontmatter(type="concept", title="Hot Cache"),
            body="# Hot Cache\n\nA rolling context file.",
        )
    )
    return bundle


async def test_mirror_writes_null_embedding_chunks(sqlite_factory, tmp_path):
    bundle = _one_page_bundle(tmp_path)
    with sqlite_factory() as s:
        await mirror_bundle(s, bundle)  # NOTE: no embed_client kwarg anymore
        s.commit()
        chunks = s.execute(select(WikiChunk)).scalars().all()
        assert len(chunks) >= 1
        assert all(c.chunk_text for c in chunks)
        assert all(c.embedding is None for c in chunks)
