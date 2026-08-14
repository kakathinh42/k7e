"""Authorization service and FastAPI dependency helpers.

Defines:
- ``Principal``: the identity of the calling user (user_id + roles).
- ``AuthorizationService``: a Protocol describing the authorization contract.
- ``OpenAuthorizationService``: MVP implementation (all items allowed; reviewer
  check by role or hardcoded 'dev' user).
- ``GroupAuthorizationService``: group-enforced implementation that filters
  source pages by ``allowed_groups`` and derived pages by their
  ``provenance.source_pages`` visibility.
- ``get_principal``: FastAPI dependency that reads ``X-User-Id`` and
  ``X-User-Roles`` request headers.
- ``get_authz``: FastAPI dependency that returns the active
  ``AuthorizationService`` instance.

Design notes
------------
* ``AuthorizationService.allowed_item_ids`` returns ``None`` to mean "all
  items allowed" – this avoids constructing a potentially huge set for the
  MVP where no item-level ACLs exist.
* Role parsing: ``X-User-Roles`` is a comma-separated string.  Leading/trailing
  whitespace is stripped from each token and empty tokens (e.g. from a trailing
  comma) are dropped.
* The ``Protocol`` approach allows tests to substitute alternative
  implementations without subclassing.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Protocol, runtime_checkable

from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from k7e_api.config import get_settings
from k7e_api.db import get_session
from k7e_api.jwt_auth import (
    JwtError,
    JwtUnavailableError,
    identity_from_claims,
    verify_token,
)
from k7e_api.models import PersonalAccessToken
from k7e_api.pat_auth import hash_pat, is_pat
from k7e_api.rbac import (  # noqa: E402  (Scope re-exported for callers)
    Scope,
    effective_groups,
)

# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


class Principal(BaseModel):
    """The authenticated caller identity.

    Attributes:
        user_id: Opaque identifier for the caller (from ``X-User-Id`` header).
        kind: ``"user"`` or ``"app"`` (M6: service-identity apps).
        roles: List of roles assigned to the caller (from ``X-User-Roles`` header).
        groups: List of access groups the caller belongs to (from ``X-User-Groups`` header).
    """

    user_id: str
    kind: str = "user"  # "user" | "app" (M6: service-identity apps)
    roles: list[str]
    groups: list[str] = []
    # True when identity was cryptographically/authoritatively established
    # (JWT-verified end user, or delegated via a trusted app), vs a raw header.
    verified: bool = False


# ---------------------------------------------------------------------------
# Authorization protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class AuthorizationService(Protocol):
    """Contract for authorization checks.

    Implementations determine which knowledge items a principal may access
    and whether they are allowed to perform review actions.
    """

    def allowed_item_ids(
        self,
        principal: Principal,
        session,  # sqlalchemy.orm.Session – typed loosely to avoid import cycle
    ) -> set[uuid.UUID] | None:
        """Return the set of item UUIDs the principal may read.

        Returns:
            ``None`` means "all items allowed" (no ACL restriction).
            A non-``None`` set contains exactly the permitted item UUIDs.
        """
        ...  # pragma: no cover

    def can_review(self, principal: Principal, scope: Scope | None = None) -> bool:
        """Return True if the principal is allowed to perform review actions.

        ``scope`` (optional) narrows the check to a containment node (org /
        space / project).  ``None`` means "reviewer anywhere" — the legacy
        semantics — so existing ``can_review(principal)`` call sites stay
        source-compatible.
        """
        ...  # pragma: no cover

    def can_write(self, principal: Principal, scope: Scope | None = None) -> bool:
        """Return True if the principal may write (ingest / edit) at ``scope``.

        ``scope`` is optional (``None`` = "write anywhere the principal is
        otherwise permitted") so call sites can adopt it incrementally.
        """
        ...  # pragma: no cover

    def can_admin(self, principal: Principal, scope: Scope | None = None) -> bool:
        """Return True if the principal may administer ``scope`` (manage
        members, settings). ``scope`` optional (``None`` = admin anywhere).
        """
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# MVP implementation
# ---------------------------------------------------------------------------


def _dev_backdoor(principal: Principal) -> bool:
    """The hardcoded ``"dev"`` user auto-passes review/write ONLY in dev env.

    M0 hardening + M6: only a ``kind == "user"`` principal can be the dev user;
    an app named ``dev`` never gets the backdoor.
    """
    return principal.kind == "user" and principal.user_id == "dev" and get_settings().env == "dev"


class OpenAuthorizationService:
    """Open authorization – MVP: all authenticated users can see all items.

    ``allowed_item_ids`` returns ``None`` (meaning "all allowed") because in
    the MVP there are no item-level ACLs.

    ``can_review`` returns True for users with the ``"reviewer"`` role **or**
    for the hardcoded ``"dev"`` user (useful for local development without a
    full auth stack).
    """

    def allowed_item_ids(
        self,
        principal: Principal,
        session,
    ) -> set[uuid.UUID] | None:
        """All items are accessible in the MVP; return None to signal no filter."""
        return None

    def can_review(self, principal: Principal, scope: Scope | None = None) -> bool:
        """Return True if the principal can review items.

        ``scope`` is ignored in open mode: the legacy "reviewer anywhere"
        check (role-or-``dev``) is preserved verbatim.
        """
        return "reviewer" in principal.roles or _dev_backdoor(principal)

    def can_write(self, principal: Principal, scope: Scope | None = None) -> bool:
        """Open mode: any authenticated principal may write."""
        return True

    def can_admin(self, principal: Principal, scope: Scope | None = None) -> bool:
        """Open mode: admin role or dev backdoor (mirrors can_review)."""
        return "admin" in principal.roles or _dev_backdoor(principal)


# ---------------------------------------------------------------------------
# Group-enforced implementation
# ---------------------------------------------------------------------------


class GroupAuthorizationService:
    """Group-based authorization.

    A source page is visible iff ``allowed_groups`` is null/empty (public) or
    intersects the caller's effective groups (declared ∪ the implicit
    ``"public"`` group ∪ the ``user:<user_id>`` self-group — see
    ``rbac.effective_groups``). A
    derived page (type != "source") is visible iff EVERY source page slug in its
    ``provenance.source_pages`` is a visible source — so compiled knowledge never
    leaks a restricted source. Returns a concrete set (never None).
    """

    def allowed_item_ids(self, principal: Principal, session) -> set[uuid.UUID] | None:
        from k7e_api.models import KnowledgeItem

        effective = effective_groups(principal)
        rows = session.execute(
            select(
                KnowledgeItem.id,
                KnowledgeItem.slug,
                KnowledgeItem.type,
                KnowledgeItem.allowed_groups,
                KnowledgeItem.provenance,
            )
            .where(KnowledgeItem.status == "published")
            .where(KnowledgeItem.current_version_id.is_not(None))
        ).all()

        def _source_visible(allowed_groups) -> bool:
            if not allowed_groups:  # None or [] → public
                return True
            return bool(set(allowed_groups) & effective)

        visible_source_slugs = {
            slug
            for (_id, slug, type_, ag, _prov) in rows
            if type_ == "source" and _source_visible(ag)
        }

        allowed: set[uuid.UUID] = set()
        for iid, slug, type_, ag, prov in rows:
            if type_ == "source":
                if _source_visible(ag):
                    allowed.add(iid)
            else:
                source_pages = (prov or {}).get("source_pages") or []
                if all(sp in visible_source_slugs for sp in source_pages):
                    allowed.add(iid)
        return allowed

    def can_review(self, principal: Principal, scope: Scope | None = None) -> bool:
        # Scope-agnostic: today's role check is unchanged. Task 3 introduces a
        # scope-aware service that walks role grants; the legacy group service
        # keeps its existing "reviewer anywhere" semantics.
        return "reviewer" in principal.roles or _dev_backdoor(principal)

    def can_write(self, principal: Principal, scope: Scope | None = None) -> bool:
        # Mirrors can_review: a reviewer (or the dev user) may write. Scope is
        # ignored — the group service remains scope-agnostic.
        return "reviewer" in principal.roles or _dev_backdoor(principal)

    def can_admin(self, principal: Principal, scope: Scope | None = None) -> bool:
        # Scope-agnostic (mirrors can_review/can_write in the group service).
        return "admin" in principal.roles or _dev_backdoor(principal)


# ---------------------------------------------------------------------------
# FastAPI dependency helpers
# ---------------------------------------------------------------------------


def _csv_header(value: object) -> list[str]:
    """Parse a comma-separated header into a clean token list.

    Tolerates a non-str default (FastAPI's ``Header`` FieldInfo) when the
    dependency is called directly outside the request path; real requests
    always pass a string.
    """
    raw = value if isinstance(value, str) else ""
    return [token.strip() for token in raw.split(",") if token.strip()]


def _bearer_token(authorization: object) -> str | None:
    """Extract the token from an ``Authorization: Bearer <token>`` header.

    Tolerates a non-str default (FastAPI's ``Header`` FieldInfo) when the
    dependency is called directly outside the request path, mirroring
    ``_csv_header``'s tolerance above.
    """
    if not isinstance(authorization, str):
        return None
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


def _principal_from_pat(token: str, session: Session | None) -> Principal:
    """Resolve a ``wpat_`` Personal Access Token to its owning user (verified).

    A non-revoked, non-expired match → ``Principal(kind="user", user_id=<owner>,
    verified=True)`` and stamps ``last_used_at``; anything else → 401. The
    revoked + expiry checks run IN SQL to avoid naive/aware datetime
    comparisons on SQLite. The PAT owner flows through the
    same RBAC / personal-space scoping as any other verified user.
    """
    if session is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    now = datetime.now(timezone.utc)
    pat = session.execute(
        select(PersonalAccessToken).where(
            PersonalAccessToken.token_hash == hash_pat(token),
            PersonalAccessToken.revoked_at.is_(None),
            or_(
                PersonalAccessToken.expires_at.is_(None),
                PersonalAccessToken.expires_at > now,
            ),
        )
    ).scalar_one_or_none()
    if pat is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    pat.last_used_at = now
    session.commit()
    return Principal(kind="user", user_id=pat.user_id, roles=[], groups=[], verified=True)


def get_principal(
    x_user_id: str | None = Header(default=None),
    x_user_roles: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    session: Annotated[Session, Depends(get_session)] = None,
) -> Principal:
    """Build a ``Principal`` from a verified Bearer JWT or request headers.

    Headers:
        X-User-Id: Caller identifier.
        X-User-Roles: Comma-separated roles.
        X-User-Groups: Comma-separated access groups. Whitespace around each
            token is stripped; empty tokens are dropped.
        Authorization: ``Bearer <jwt>`` — verified when ``jwt_enabled`` (M7).

    M7 — when ``jwt_enabled``: a valid Bearer token wins, becoming
    ``Principal(user_id=<sub>, roles=[], groups=[])`` (roles/groups are
    DB-resolved elsewhere, e.g. team membership). An invalid/expired token
    raises 401. With no Bearer token, prod ignores the ``X-User-*`` seam
    (fails closed to anonymous) while dev falls through to it below for
    local convenience.

    M0 hardening — env-gated defaults. When a header is absent:

    * ``env == "dev"`` (local): fall back to the convenient ``dev`` /
      ``reviewer`` identity so local development needs no auth stack.
    * any other env (prod/staging): fall back to an **anonymous** identity
      (``user_id="anonymous"``, no roles, no groups) so a missing gateway
      identity fails **closed** — RBAC then admits nothing and gates every
      write/review — instead of silently granting reviewer access.
    """
    settings = get_settings()
    is_dev = settings.env == "dev"

    # getattr: some tests substitute a minimal settings stub exposing only
    # ``env`` (predating M7); treat a missing attribute as JWT-disabled.
    if getattr(settings, "jwt_enabled", False):
        token = _bearer_token(authorization)
        if token is not None:
            # A wpat_ Personal Access Token resolves to its owning user; any
            # other Bearer is verified as a JWT/session below (unchanged).
            if is_pat(token):
                return _principal_from_pat(token, session)
            try:
                claims = verify_token(token, settings)
                user_id = identity_from_claims(claims, settings)
            except JwtUnavailableError as exc:
                # JWKS/IdP outage → retryable, not a bad token.
                raise HTTPException(
                    status_code=503,
                    detail="Identity verification temporarily unavailable",
                ) from exc
            except JwtError as exc:
                raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
            return Principal(user_id=user_id, roles=[], groups=[])
        # No token: prod ignores the X-User-* seam (fail closed to anonymous);
        # dev falls through to the header seam below for local convenience.
        if not is_dev:
            return Principal(user_id="anonymous", roles=[], groups=[])

    user_id = x_user_id if x_user_id is not None else ("dev" if is_dev else "anonymous")
    if x_user_roles is not None:
        roles = _csv_header(x_user_roles)
    else:
        roles = ["reviewer"] if is_dev else []
    groups = _csv_header(x_user_groups) if x_user_groups is not None else []
    return Principal(user_id=user_id, roles=roles, groups=groups)


def require_verified_identity(principal: Principal, settings) -> None:
    """403 unless the principal's identity is trustworthy for personal data.

    dev env: header identities allowed (local/test convenience). Any other
    env: only a JWT-verified principal passes. No flag is needed — when
    ``jwt_enabled`` and env != dev, get_principal forces header callers to
    ``anonymous`` before the header seam, so any non-anonymous user principal
    necessarily came from a verified token. With ``jwt_enabled`` off outside
    dev there is no verification at all → always 403.
    """
    if settings.env == "dev":
        return
    is_user = principal.kind == "user" and principal.user_id not in ("", "anonymous")
    verified = is_user and (
        getattr(settings, "jwt_enabled", False)  # JWT-verified end user (M7)
        or getattr(principal, "verified", False)  # delegated via a trusted app
    )
    if not verified:
        raise HTTPException(
            status_code=403, detail="Verified identity required for personal ingest"
        )


def get_principal_with_teams(
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> Principal:
    """Return a Principal with team groups resolved from Membership.

    Wraps ``get_principal`` (pure header reader) and unions
    ``team_groups_for_user(session, principal.user_id)`` into ``principal.groups``
    so the RBAC resolver's group-grant match admits team members automatically.
    Use this dep for routers whose authorization depends on team membership
    (read paths: /items, /search, /graph). ``get_principal`` stays pure
    for paths that don't need team-aware groups (e.g. /teams management, where
    ``can_admin`` checks user grants and membership is queried directly).

    Resolved per-request from the memberships table — removing a member cuts
    access on the next request (no cached grant).
    """
    from k7e_api.teams import team_groups_for_user  # lazy: avoid import cycle

    team_groups = team_groups_for_user(session, principal.user_id)
    if not team_groups:
        return principal  # no memberships → unchanged (avoids a copy)
    return principal.model_copy(update={"groups": [*principal.groups, *team_groups]})


def get_authz() -> AuthorizationService:
    """Return the active AuthorizationService.

    Selected by ``Settings.auth_mode``:

    * ``"rbac"`` (default, M2) — the hierarchical RBAC service (role grants +
      downward scope inheritance). Lazy-imported to avoid an import cycle
      (``k7e_api.rbac`` imports models, which other auth-path modules reach).
    * ``"groups"`` — the legacy Piece-1 group-enforced service. Also selected
      when ``auth_enforce_groups`` is True, so deployments that still set
      ``AUTH_ENFORCE_GROUPS=true`` keep their prior behavior.
    * ``"open"`` — fully-open authorization (local/dev).
    """
    s = get_settings()
    if s.auth_mode == "rbac":
        from k7e_api.rbac import (
            HierarchicalRbacAuthorizationService,
        )  # lazy (avoid cycle)

        return HierarchicalRbacAuthorizationService()
    if s.auth_mode == "groups" or s.auth_enforce_groups:  # legacy Piece-1 mode
        return GroupAuthorizationService()
    return OpenAuthorizationService()
