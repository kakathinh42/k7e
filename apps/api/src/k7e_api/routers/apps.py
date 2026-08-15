"""Apps router: org-admin provisioning of ClientApp service identities (M6).

POST /apps creates a ClientApp, seeds a default editor@org grant (service
identity), and returns the plaintext X-App-Key ONCE. GET /apps lists the org's
apps (never the key). Admin-gated on the org.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from k7e_api.app_auth import generate_app_key
from k7e_api.auth import (
    AuthorizationService,
    Principal,
    Scope,
    get_authz,
    get_principal,
)
from k7e_api.db import get_session
from k7e_api.models import ClientApp, RoleGrant
from k7e_api.schemas import AppCreate, AppOut, AppSummary
from k7e_api.tenancy import TenantContext, get_tenant_context, scoped

router = APIRouter()


@router.post("", response_model=AppOut, status_code=status.HTTP_201_CREATED)
def create_app(
    body: AppCreate,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    authz: Annotated[AuthorizationService, Depends(get_authz)],
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
) -> AppOut:
    """Provision a ClientApp (org-admin only). Returns the key once."""
    if not authz.can_admin(principal, Scope("org", ctx.org_id)):
        raise HTTPException(status_code=403, detail="Admin role required")

    plaintext, key_hash = generate_app_key()
    app = ClientApp(org_id=ctx.org_id, slug=body.slug, name=body.name, api_key_hash=key_hash)
    session.add(app)
    try:
        session.flush()
        session.add(
            RoleGrant(
                principal_kind="app",
                principal_id=body.slug,
                role="editor",
                scope_kind="org",
                scope_id=ctx.org_id,
            )
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="App slug already exists")

    return AppOut(
        id=app.id,
        slug=app.slug,
        name=app.name,
        org_id=app.org_id,
        created_at=app.created_at,
        api_key=plaintext,
    )


@router.get("", response_model=list[AppSummary])
def list_apps(
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    authz: Annotated[AuthorizationService, Depends(get_authz)],
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
) -> list[AppSummary]:
    """List the org's ClientApps (never the key). Org-admin only."""
    if not authz.can_admin(principal, Scope("org", ctx.org_id)):
        raise HTTPException(status_code=403, detail="Admin role required")
    apps = (
        session.execute(scoped(select(ClientApp).order_by(ClientApp.created_at), ctx, ClientApp))
        .scalars()
        .all()
    )
    return [
        AppSummary(id=a.id, slug=a.slug, name=a.name, org_id=a.org_id, created_at=a.created_at)
        for a in apps
    ]
