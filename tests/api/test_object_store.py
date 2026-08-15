"""Tests for k7e_api.object_store module.

Covers:
- LocalFileObjectStore put/get roundtrip
- sha256_key stability and format
"""

from k7e_api.object_store import LocalFileObjectStore, sha256_key


def test_put_get_roundtrip(tmp_path):
    store = LocalFileObjectStore(str(tmp_path))
    ref = store.put("raw/demo.md", b"hello")
    assert store.get("raw/demo.md") == b"hello"
    assert ref.endswith("raw/demo.md")


def test_sha256_key_is_stable():
    assert sha256_key(b"hello") == sha256_key(b"hello")
    assert sha256_key(b"hello").startswith("sha256:")
