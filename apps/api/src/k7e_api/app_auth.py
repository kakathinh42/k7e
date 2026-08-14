"""M6: app (service-identity) authentication via an X-App-Key header.

Provisioning returns a high-entropy random key once; only its sha256 hash is
stored. A request presents ``X-App-Key: <key>``; we hash + look up the
ClientApp and (in routes) build a Principal(kind="app", user_id=<slug>).
Distinct from Authorization: Bearer so it composes with M7's end-user JWT.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Annotated

import structlog
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from k7e_api.auth import Principal, get_principal
from k7e_api.db import get_session
from k7e_api.jwt_auth import normalize_identity
from k7e_api.models import ClientApp
from k7e_api.tenancy import TenantContext, get_tenant_context

logger = structlog.get_logger(__name__)

_KEY_PREFIX = "wapp_"


def generate_app_key() -> tuple[str, str]:
    """Return ``(plaintext_key, sha256_hex)``. Store only the hash."""
    plaintext = _KEY_PREFIX + secrets.token_urlsafe(32)
    return plaintext, hash_app_key(plaintext)


def hash_app_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def get_app(
    x_app_key: Annotated[str | None, Header()] = None,
    session: Annotated[Session, Depends(get_session)] = None,
) -> ClientApp:
    """Resolve the ``X-App-Key`` header to the authenticated ClientApp (401 else)."""
    if not x_app_key:
        raise HTTPException(status_code=401, detail="Missing X-App-Key")
    app = session.execute(
        select(ClientApp).where(ClientApp.api_key_hash == hash_app_key(x_app_key))
    ).scalar_one_or_none()
    if app is None:
        raise HTTPException(status_code=401, detail="Invalid X-App-Key")
    return app


def app_principal(app: ClientApp) -> Principal:
    """Build the service-identity Principal for an authenticated app."""
    return Principal(kind="app", user_id=app.slug, roles=[], groups=[])


def get_effective_principal(
    x_app_key: Annotated[str | None, Header()] = None,
    x_on_behalf_of_email: Annotated[str | None, Header()] = None,
    session: Annotated[Session, Depends(get_session)] = None,
    principal: Annotated[Principal, Depends(get_principal)] = None,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)] = None,
) -> Principal:
    """Identity for endpoints a trusted app may call on a user's behalf.

    An authenticated, delegation-allowed ClientApp that sends BOTH ``X-App-Key``
    and ``X-On-Behalf-Of-Email`` runs AS that verified end user. For any other
    caller the on-behalf header is IGNORED and the normal principal (JWT / header
    / dev, via ``get_principal``) is returned — an arbitrary caller can never
    self-assert an identity.

    ``ctx`` (the resolved ``TenantContext``) is optional so direct-call unit
    tests that skip it keep working; real requests always inject it. When
    present, a delegation-allowed app may only assert an identity within its
    own org — it must not reach across org boundaries even though
    ``get_tenant_context`` itself is not yet caller-controllable (F4).
    """
    if x_app_key and x_on_behalf_of_email:
        app = session.execute(
            select(ClientApp).where(ClientApp.api_key_hash == hash_app_key(x_app_key))
        ).scalar_one_or_none()
        if app is not None and app.can_delegate_identity:
            raw = x_on_behalf_of_email.strip()
            local, sep, domain = raw.partition("@")
            if (
                not sep
                or not local
                or not domain
                or "@" in domain  # rejects a@b@example.com
                or any(c.isspace() for c in raw)  # rejects embedded whitespace/newlines
            ):
                raise HTTPException(status_code=400, detail="Invalid X-On-Behalf-Of-Email")
            email = normalize_identity(raw)  # lowercased
            if app.allowed_identity_domain and not email.endswith(
                "@" + app.allowed_identity_domain.lower()
            ):
                raise HTTPException(
                    status_code=403, detail="App may not assert this identity domain"
                )
            if ctx is None or app.org_id != ctx.org_id:
                raise HTTPException(
                    status_code=403,
                    detail="App may not assert an identity outside its org",
                )
            logger.info(
                "delegated_identity",
                app=app.slug,
                email_sha256=hashlib.sha256(email.encode()).hexdigest()[:16],
            )
            return Principal(kind="user", user_id=email, roles=[], groups=[], verified=True)
    return principal


def get_effective_principal_with_teams(
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_effective_principal)],
) -> Principal:
    """Read-path identity for retrieval: resolve the (possibly delegated)
    effective principal, then union the caller's team groups from Membership.

    Same team-union behavior as ``auth.get_principal_with_teams`` but built on
    ``get_effective_principal`` so a chat-agent on-behalf retrieval is scoped to
    the end user's teams. A non-delegated caller falls through to the normal
    principal, so behavior is unchanged for everyone else.
    """
    from k7e_api.teams import team_groups_for_user  # lazy: avoid import cycle

    team_groups = team_groups_for_user(session, principal.user_id)
    if not team_groups:
        return principal
    return principal.model_copy(update={"groups": [*principal.groups, *team_groups]})
