"""Personal Access Token endpoints — create / list / revoke (session-authed).

The caller authenticates as a user (session/JWT Bearer via get_principal); a PAT
is minted for that user, the plaintext is returned ONCE, and only its sha256 is
stored. Listing never returns the plaintext; revoke is soft (revoked_at) and
owner-scoped.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from k7e_api.auth import Principal, get_principal
from k7e_api.db import get_session
from k7e_api.models import PersonalAccessToken
from k7e_api.pat_auth import generate_pat

router = APIRouter()


def _require_user(principal: Principal) -> str:
    """Return the authenticated user's id, or 401 for anonymous/non-user callers."""
    if principal.kind != "user" or principal.user_id in ("", "anonymous"):
        raise HTTPException(status_code=401, detail="Authentication required")
    return principal.user_id


class PatCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    # bounded so an absurd value is a clean 422, not an OverflowError 500.
    expires_days: Optional[int] = Field(default=None, ge=1, le=3650)


class PatCreateOut(BaseModel):
    id: str
    name: str
    token: str
    expires_at: Optional[datetime] = None


class PatOut(BaseModel):
    id: str
    name: str
    created_at: datetime
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None


@router.post("", response_model=PatCreateOut)
def create_pat(
    body: PatCreateIn,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> PatCreateOut:
    user_id = _require_user(principal)
    plaintext, token_hash = generate_pat()
    expires_at: Optional[datetime] = None
    if body.expires_days is not None and body.expires_days > 0:
        expires_at = datetime.now(timezone.utc) + timedelta(days=body.expires_days)
    pat = PersonalAccessToken(
        user_id=user_id,
        name=body.name,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    session.add(pat)
    session.commit()
    return PatCreateOut(id=str(pat.id), name=pat.name, token=plaintext, expires_at=expires_at)


@router.get("", response_model=list[PatOut])
def list_pat(
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> list[PatOut]:
    user_id = _require_user(principal)
    rows = (
        session.execute(
            select(PersonalAccessToken)
            .where(PersonalAccessToken.user_id == user_id)
            .order_by(PersonalAccessToken.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [
        PatOut(
            id=str(r.id),
            name=r.name,
            created_at=r.created_at,
            last_used_at=r.last_used_at,
            expires_at=r.expires_at,
            revoked_at=r.revoked_at,
        )
        for r in rows
    ]


@router.delete("/{pat_id}", status_code=204)
def revoke_pat(
    pat_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> None:
    user_id = _require_user(principal)
    try:
        pid = uuid.UUID(pat_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    pat = session.execute(
        select(PersonalAccessToken).where(
            PersonalAccessToken.id == pid,
            PersonalAccessToken.user_id == user_id,
        )
    ).scalar_one_or_none()
    if pat is None:
        raise HTTPException(status_code=404, detail="Not found")
    if pat.revoked_at is None:
        pat.revoked_at = datetime.now(timezone.utc)
        session.commit()
