from k7e_api.connectors.base import FetchedDocument
from k7e_api.connectors.filesystem import FilesystemConnector


def test_filesystem_connector_yields_documents(tmp_path):
    (tmp_path / "a.md").write_text("# Alpha")
    (tmp_path / "b.md").write_text("# Beta")
    (tmp_path / "skip.png").write_bytes(b"\x89PNG")

    conn = FilesystemConnector(root=str(tmp_path), patterns=["*.md"])
    docs = list(conn.fetch())

    assert conn.name == "filesystem"
    assert len(docs) == 2
    assert all(isinstance(d, FetchedDocument) for d in docs)
    ids = sorted(d.source_external_id for d in docs)
    assert ids == ["a.md", "b.md"]
    doc_a = next(d for d in docs if d.source_external_id == "a.md")
    assert doc_a.content == b"# Alpha"
    assert doc_a.source_system == "filesystem"
    assert doc_a.source_tier == "A"
