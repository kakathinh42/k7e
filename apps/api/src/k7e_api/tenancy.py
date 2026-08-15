"""Tenant scoping — the single seam every multi-org query passes through.

Design intent
-------------
``scoped()`` is the ONE place where the ``org_id`` predicate is applied to
SQLAlchemy SELECT statements.  All tenant-scoped queries must go through it;
nothing else in the codebase is permitted to add ``where(model.org_id == ...)``
directly.  This discipline guarantees:

- A single audit point for tenant isolation.
- A clean upgrade path: in Phase 5 ``TenantContext`` becomes per-request
  (populated from JWT token claims or ``X-Org`` header) — **call sites never
  change**.

Phase 1 behaviour
-----------------
``get_tenant_context()`` resolves the *single* default organisation (slug
``Settings.default_org_slug``, currently ``"default"``).  The returned
``TenantContext`` is then passed directly into ``scoped()`` at query sites.

Null-org_id rows (Phase 1 backward compat)
------------------------------------------
Rows written before the tenant migration (0016) have ``org_id = NULL``.  In
Phase 1 (single-tenant mode) those rows are implicitly owned by the default
org.  ``scoped()`` therefore returns rows whose ``org_id`` matches *or* is
``NULL`` so that pre-migration data stays visible.  Phase 5 (hard multi-tenant)
will tighten this to exact equality once all rows are backfilled.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from k7e_api.config import get_settings
from k7e_api.db import get_session
from k7e_api.models import KnowledgeItem, Organization


@dataclass(frozen=True)
class TenantContext:
    """Immutable carrier of tenant identity for a single request / call scope.

    ``org_id`` is the primary key of the resolved ``Organization`` row.  All
    ``scoped()`` calls use this value to filter query results to the owning org.

    Frozen so it can be safely cached or passed across async boundaries.
    """

    org_id: uuid.UUID


def scoped(stmt, ctx: TenantContext, model: type = KnowledgeItem):
    """Return *stmt* with an ``org_id`` predicate appended.

    Phase 1 predicate: ``WHERE model.org_id = ctx.org_id OR model.org_id IS NULL``

    The ``IS NULL`` arm is the Phase 1 backward-compat clause: rows written
    before the tenant seed migration have no org_id and are implicitly owned by
    the default org.  This makes the seam transparent at one tenant — the
    regression suite proves it.

    Phase 5 upgrade: tighten to exact equality (``org_id = ctx.org_id`` only)
    once all rows have been backfilled.  The call sites don't change.

    This is the ONE place org scoping is applied.  Every tenant-scoped query
    **must** go through this function — no router or service is permitted to
    write ``where(SomeModel.org_id == ...)`` directly.

    Parameters
    ----------
    stmt:
        A SQLAlchemy ``Select`` (or any statement that supports ``.where()``).
    ctx:
        The ``TenantContext`` for the current request / caller scope.
    model:
        The ORM model class whose ``org_id`` column is used for filtering.
        Defaults to ``KnowledgeItem`` for convenience; pass the appropriate
        model when scoping ``RawDocument``, ``WikiChunk``, etc.

    Returns
    -------
    The same statement type with an additional ``WHERE`` clause.
    """
    return stmt.where(or_(model.org_id == ctx.org_id, model.org_id.is_(None)))


def get_tenant_context(session: Session = Depends(get_session)) -> TenantContext:
    """FastAPI dependency: resolve the active ``TenantContext``.

    Phase 1 — single-tenant mode
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Looks up the Organization whose ``slug`` matches ``Settings.default_org_slug``
    (default: ``"default"``).  Raises ``ValueError`` if no such org exists so
    that the error is visible immediately at startup rather than as a silent
    query-returns-nothing failure.

    Phase 5 upgrade point
    ~~~~~~~~~~~~~~~~~~~~~
    Replace the slug lookup with a JWT claim or ``X-Org`` header read.  The
    function signature stays the same; every call site is unaffected.
    """
    settings = get_settings()
    org = session.execute(
        select(Organization).where(Organization.slug == settings.default_org_slug)
    ).scalar_one_or_none()

    if org is None:
        raise ValueError(
            f"Default organisation {settings.default_org_slug!r} not found in the database. "
            "Ensure the tenant seed migration (0016) has been applied."
        )

    return TenantContext(org_id=org.id)
