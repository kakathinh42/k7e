from k7e_api.chunking import chunk_markdown


def test_short_text_is_single_chunk():
    assert chunk_markdown("# Title\n\nshort body") == ["# Title\n\nshort body"]


def test_long_text_splits_with_overlap():
    body = "\n\n".join(f"Paragraph {i} " + "word " * 60 for i in range(10))
    chunks = chunk_markdown(body, max_chars=400, overlap_chars=80)
    assert len(chunks) > 1
    assert all(len(c) <= 400 + 80 for c in chunks)
    assert all(c.strip() for c in chunks)


def test_empty_text_yields_no_chunks():
    assert chunk_markdown("") == []
    assert chunk_markdown("   \n  ") == []
