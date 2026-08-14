"""Native authentication endpoints (email + password).

/auth/register — create a native account (domain-gated) and log in.
/auth/login    — verify email + password → a self-issued session.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from k7e_api.config import get_settings
from k7e_api.db import get_session
from k7e_api.jwt_auth import JwtError, normalize_identity, verify_token
from k7e_api.models import User
from k7e_api.password_auth import DUMMY_HASH, hash_password, verify_password
from k7e_api.session_auth import mint_session
from k7e_api.tenancy import TenantContext, get_tenant_context

router = APIRouter()


class SessionOut(BaseModel):
    session_token: str


class CredentialsIn(BaseModel):
    email: str
    password: str


@router.post("/register", response_model=SessionOut)
def auth_register(
    body: CredentialsIn,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    session: Annotated[Session, Depends(get_session)],
) -> SessionOut:
    """Register a native account (domain-gated) and log the user straight in.

    The email must match ``registration_allowed_domain`` (if set) and the
    password meet ``password_min_length``; only the bcrypt hash is stored.
    """
    settings = get_settings()
    email = normalize_identity(body.email.strip())
    local, _, _ = email.partition("@")
    domain = settings.registration_allowed_domain.lower()
    if email.count("@") != 1 or not local or (domain and not email.endswith("@" + domain)):
        raise HTTPException(status_code=400, detail="Email not allowed")
    if len(body.password) < settings.password_min_length:
        raise HTTPException(status_code=400, detail="Password too short")
    # bcrypt raises over 72 BYTES (not chars) — validate to a clean 400, not 500.
    if len(body.password.encode("utf-8")) > settings.password_max_bytes:
        raise HTTPException(status_code=400, detail="Password too long")
    if session.execute(select(User).where(User.email == email)).scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Already registered")
    session.add(
        User(
            email=email,
            password_hash=hash_password(body.password),
            org_id=ctx.org_id,
        )
    )
    session.commit()
    return SessionOut(session_token=mint_session(email, settings))


@router.post("/login", response_model=SessionOut)
def auth_login(
    body: CredentialsIn,
    session: Annotated[Session, Depends(get_session)],
) -> SessionOut:
    """Verify email+password → a self-issued session. Generic 401 on any failure
    (no user-enumeration: unknown user and wrong password look identical)."""
    settings = get_settings()
    email = normalize_identity(body.email.strip())
    user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
    # Constant-time: ALWAYS run exactly one bcrypt compare (a dummy hash when the
    # account doesn't exist) so login timing can't reveal whether an email is
    # registered.
    stored = user.password_hash if user is not None else DUMMY_HASH
    ok = verify_password(body.password, stored)
    if user is None or not ok:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return SessionOut(session_token=mint_session(email, settings))


@router.post("/refresh", response_model=SessionOut)
def auth_refresh(
    session: Annotated[Session, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> SessionOut:
    """Re-mint an active session before its JWT expires (silent client refresh).

    Only a first-party SESSION token can refresh: ``verify_token`` rejects a
    PAT (opaque) outright, and we additionally REQUIRE ``iss == session_issuer``
    so an external IdP JWT (different ``iss``) can't be upgraded into a session
    — no type/privilege confusion. An expired token raises in ``verify_token``
    → 401 by design; the client refreshes *before* expiry. Generic 401 detail
    (no enumeration)."""
    detail = "Authentication required"
    token = (authorization or "").strip()
    if token[:7].lower() == "bearer ":
        token = token[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail=detail)

    settings = get_settings()
    try:
        claims = verify_token(token, settings)
    except JwtError as exc:
        raise HTTPException(status_code=401, detail=detail) from exc

    if claims.get("iss") != settings.session_issuer:
        raise HTTPException(status_code=401, detail=detail)

    email = normalize_identity(str(claims.get("sub") or claims.get("email") or "").strip())
    if not email:
        raise HTTPException(status_code=401, detail=detail)

    # Re-verify the account still exists (like /login) — a valid signature over a
    # not-yet-expired token must NOT let a deleted/disabled user keep minting
    # fresh 8h sessions forever.
    user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail=detail)

    return SessionOut(session_token=mint_session(email, settings))
