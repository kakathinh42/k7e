"""Connectors router: admin-triggered source sync for a Space.

POST /connectors/{space_slug}/sync builds the Space's configured connector
(from Space.connector_config + the API token in settings) and runs it through
the idempotent ingest pipeline, stamping the Space's org + config-default
allowed_groups on every document. Admin-gated on the Space.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from k7e_api.auth import (
    AuthorizationService,
    Principal,
    Scope,
    get_authz,
    get_principal,
)
from k7e_api.config import Settings, get_settings
from k7e_api.connectors.registry import build_connector, connector_defaults
from k7e_api.db import get_session
from k7e_api.deps import get_object_store, get_workflow_starter
from k7e_api.ingest_service import as_sync_workflow_starter, run_connector
from k7e_api.models import Space
from k7e_api.schemas import ConnectorSyncResult
from k7e_api.tenancy import TenantContext, get_tenant_context, scoped

router = APIRouter()


@router.post("/{space_slug}/sync", response_model=ConnectorSyncResult)
def sync_connector(
    space_slug: str,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    authz: Annotated[AuthorizationService, Depends(get_authz)],
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    object_store: Annotated[object, Depends(get_object_store)],
    workflow_starter: Annotated[object, Depends(get_workflow_starter)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ConnectorSyncResult:
    """Run the Space's configured connector once (admin only)."""
    space = session.execute(
        scoped(select(Space).where(Space.slug == space_slug), ctx, Space)
    ).scalar_one_or_none()
    if space is None:
        raise HTTPException(status_code=404, detail="Space not found")

    if not authz.can_admin(principal, Scope("space", space.id)):
        raise HTTPException(status_code=403, detail="Admin role required")

    try:
        connector = build_connector(space, settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    result = run_connector(
        session,
        object_store,
        as_sync_workflow_starter(workflow_starter),
        connector,
        org_id=space.org_id,
        allowed_groups=connector_defaults(space).get("allowed_groups"),
    )
    return ConnectorSyncResult(**result)
