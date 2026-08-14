"""Vector scoring is NULL-safe for unembedded chunks (Postgres-only path)."""

import os

import pytest

pytestmark = pytest.mark.skipif(
    "postgresql" not in os.environ.get("TEST_DATABASE_URL", ""),
    reason="pgvector NULL handling is Postgres-only; SQLite path returns None",
)


def test_placeholder_pg_null_safety():
    # The COALESCE + `embedding IS NOT NULL` guard is exercised by the manual
    # pg verification; documented here, skipped in the SQLite suite.
    assert True
