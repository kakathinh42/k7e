"""Object store abstraction for binary blob persistence.

Defines:
- ObjectStore: Protocol for pluggable object storage backends.
- LocalFileObjectStore: Stores blobs on the local filesystem under a base directory.
- sha256_key: Helper that returns a deterministic content-addressed key.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol, runtime_checkable


def sha256_key(data: bytes) -> str:
    """Return a deterministic content-addressed key for *data*.

    The key has the format ``sha256:<hex_digest>``.  It is stable across
    identical inputs and can be used as an object-store key or lookup token.

    >>> sha256_key(b"hello").startswith("sha256:")
    True
    >>> sha256_key(b"hello") == sha256_key(b"hello")
    True
    """
    return "sha256:" + hashlib.sha256(data).hexdigest()


@runtime_checkable
class ObjectStore(Protocol):
    """Protocol for binary object storage backends.

    Implementations must be substitutable (Liskov).  The local filesystem
    implementation is used in development and CI; an S3-compatible
    implementation can be plugged in later without changing callers.
    """

    def put(self, key: str, data: bytes) -> str:
        """Persist *data* under *key* and return the canonical storage reference.

        The returned reference is implementation-specific (e.g., an absolute
        path or an S3 URI) but must be non-empty and stable for the same key.
        """
        ...

    def get(self, key: str) -> bytes:
        """Return the bytes previously stored under *key*.

        Raises ``FileNotFoundError`` (or an equivalent) if the key does not
        exist in the store.
        """
        ...


class LocalFileObjectStore:
    """Filesystem-backed object store.

    Files are stored at ``<base_dir>/<key>`` where *key* may include path
    separators (e.g. ``"raw/demo.md"``).  Parent directories are created
    automatically on :py:meth:`put`.

    Args:
        base_dir: Absolute or relative path to the root storage directory.
                  The directory need not exist in advance; it will be created
                  lazily on the first :py:meth:`put` call.

    Example::

        store = LocalFileObjectStore("/data/objects")
        ref = store.put("raw/notes.md", b"# Notes")
        assert store.get("raw/notes.md") == b"# Notes"
    """

    def __init__(self, base_dir: str) -> None:
        self._base = Path(base_dir)

    def _full_path(self, key: str) -> Path:
        """Resolve *key* to an absolute path inside the base directory."""
        return self._base / key

    def put(self, key: str, data: bytes) -> str:
        """Write *data* to the store under *key*.

        Creates parent directories as needed.

        Args:
            key: Relative path within the store (e.g. ``"raw/demo.md"``).
            data: Raw bytes to persist.

        Returns:
            The absolute path string where the data was written.
        """
        dest = self._full_path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return str(dest.resolve())

    def get(self, key: str) -> bytes:
        """Read and return the bytes stored under *key*.

        Args:
            key: Relative path within the store (e.g. ``"raw/demo.md"``).

        Returns:
            The raw bytes previously written by :py:meth:`put`.

        Raises:
            FileNotFoundError: If the key has not been stored.
        """
        return self._full_path(key).read_bytes()
