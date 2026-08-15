"""Tests for TenantContext + scoped() seam helper (Task 3 — M1 multi-org).

Two concerns are verified:
1. SQL correctness — the compiled statement contains an org_id predicate.
2. Isolation correctness — rows from two orgs are separable through scoped().
"""

from __future__ import annotations

import uuid

from k7e_api.models import KnowledgeItem, Organization
from k7e_api.tenancy import TenantContext, scoped
from sqlalchemy import select
from sqlalchemy.dialects import sqlite

# ---------------------------------------------------------------------------
# SQL-level assertion: compiled statement contains org_id predicate
# ---------------------------------------------------------------------------


def test_scoped_sql_contains_org_id_predicate():
    """scoped() must add an org_id WHERE clause to the statement.

    We check the compiled SQL string so this test needs no DB connection.
    Specifically, we assert that the WHERE clause contains "org_id" — not
    just that "org_id" appears anywhere in the SQL (it's also a selected column).
    """
    org_id = uuid.uuid4()
    ctx = TenantContext(org_id=org_id)

    stmt = scoped(select(KnowledgeItem), ctx)
    compiled = stmt.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True})
    sql = str(compiled)

    # Assert the WHERE clause is present and contains the org_id predicate.
    # Using "WHERE" + "org_id" together avoids a false positive from the SELECT list.
    assert "WHERE" in sql, f"Expected a WHERE clause in compiled SQL, got:\n{sql}"
    where_clause = sql[sql.index("WHERE") :]
    assert "org_id" in where_clause, (
        f"Expected 'org_id' in WHERE clause, got WHERE portion:\n{where_clause}"
    )


# ---------------------------------------------------------------------------
# Isolation assertion: two orgs' rows are separable
# ---------------------------------------------------------------------------


def test_scoped_isolates_rows_by_org(sqlite_factory):
    """scoped() must return only the org's own KnowledgeItems.

    Seed two orgs each with one KnowledgeItem.  Verify that scoped() for org A
    returns only org A's item, and vice versa.
    """
    with sqlite_factory() as session:
        # Seed two orgs
        org_a = Organization(slug="org-a", name="Org A")
        org_b = Organization(slug="org-b", name="Org B")
        session.add_all([org_a, org_b])
        session.flush()

        # Seed one KnowledgeItem per org
        item_a = KnowledgeItem(
            org_id=org_a.id,
            slug="item-a",
            title="Item A",
            status="published",
        )
        item_b = KnowledgeItem(
            org_id=org_b.id,
            slug="item-b",
            title="Item B",
            status="published",
        )
        session.add_all([item_a, item_b])
        session.flush()

        # Verify org A context returns only item_a
        ctx_a = TenantContext(org_id=org_a.id)
        results_a = session.execute(scoped(select(KnowledgeItem), ctx_a)).scalars().all()
        assert len(results_a) == 1, f"Expected 1 item for org A, got {len(results_a)}"
        assert results_a[0].slug == "item-a"

        # Verify org B context returns only item_b
        ctx_b = TenantContext(org_id=org_b.id)
        results_b = session.execute(scoped(select(KnowledgeItem), ctx_b)).scalars().all()
        assert len(results_b) == 1, f"Expected 1 item for org B, got {len(results_b)}"
        assert results_b[0].slug == "item-b"


def test_scoped_with_explicit_model(sqlite_factory):
    """scoped() accepts an explicit model= argument.

    Passing model=KnowledgeItem explicitly must behave identically to the default.
    """
    with sqlite_factory() as session:
        org = Organization(slug="my-org", name="My Org")
        session.add(org)
        session.flush()

        item = KnowledgeItem(
            org_id=org.id,
            slug="my-item",
            title="My Item",
            status="published",
        )
        session.add(item)
        session.flush()

        ctx = TenantContext(org_id=org.id)
        results = (
            session.execute(scoped(select(KnowledgeItem), ctx, model=KnowledgeItem))
            .scalars()
            .all()
        )
        assert len(results) == 1
        assert results[0].slug == "my-item"


def test_scoped_no_cross_contamination(sqlite_factory):
    """An org with no items sees an empty result set through scoped()."""
    with sqlite_factory() as session:
        org_empty = Organization(slug="empty-org", name="Empty Org")
        org_full = Organization(slug="full-org", name="Full Org")
        session.add_all([org_empty, org_full])
        session.flush()

        # Only add items under org_full
        for i in range(3):
            session.add(
                KnowledgeItem(
                    org_id=org_full.id,
                    slug=f"item-{i}",
                    title=f"Item {i}",
                    status="published",
                )
            )
        session.flush()

        # Empty org sees nothing
        ctx_empty = TenantContext(org_id=org_empty.id)
        results = session.execute(scoped(select(KnowledgeItem), ctx_empty)).scalars().all()
        assert results == [], f"Expected no items for empty org, got {results}"

        # Full org sees all 3 of its items
        ctx_full = TenantContext(org_id=org_full.id)
        results_full = session.execute(scoped(select(KnowledgeItem), ctx_full)).scalars().all()
        assert len(results_full) == 3
