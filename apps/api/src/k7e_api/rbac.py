"""Hierarchical RBAC service (M2).

Scope-aware authorization behind the AuthorizationService seam. The grant-walk
+ downward-inheritance logic lives here (isolated as the future ReBAC swap
point); auth.py keeps the Protocol, Principal, legacy services, and deps.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import and_, or_, select

ScopeKind = Literal["org", "space", "project"]


@dataclass(frozen=True)
class Scope:
    """A containment node a role can be granted at. Distinct from TenantContext
    (which carries only org_id) — a Scope can name a space or project."""

    kind: ScopeKind
    id: uuid.UUID


# Roles form a total order; each implies the ones below for read.
_ROLE_RANK = {"viewer": 0, "editor": 1, "reviewer": 2, "admin": 3}


def role_at_least(grant_role: str, minimum: str) -> bool:
    """True iff grant_role >= minimum in the role ordering."""
    return _ROLE_RANK.get(grant_role, -1) >= _ROLE_RANK[minimum]


def effective_groups(principal) -> set[str]:
    """Groups usable for allowed_groups filtering: declared ∪ public ∪ self.

    Every human principal implicitly carries ``user:<user_id>`` so items
    stamped ``allowed_groups=["user:alice"]`` are visible ONLY to alice —
    not even org admins see them (the documented personal-spaces deviation:
    ``allowed_groups`` is a hard post-grant filter). Anonymous/app principals
    get no self-group. This feeds ONLY the ``allowed_groups`` intersection,
    never grant matching (``_matching_grants`` computes its own set).
    """
    groups = set(principal.groups) | {"public"}
    if principal.kind == "user" and principal.user_id not in ("", "anonymous"):
        groups.add(f"user:{principal.user_id}")
    return groups


class HierarchicalRbacAuthorizationService:
    """Resolve read/write access from hierarchical role grants.

    ``allowed_item_ids`` implements the spec §3 6-step resolver: match grants →
    expand scopes downward (org ⊃ spaces ⊃ projects) → admit published items
    under any covered scope → apply the ``allowed_groups`` per-page override →
    apply the derived most-restrictive rule → return the concrete set (never
    ``None``). Steps 4–5 (``_source_visible`` + the derived-page loop) reuse the
    ``GroupAuthorizationService`` logic verbatim, but applied to the
    grant-admitted subset (not every published row) so a derived page can never
    leak a source outside the caller's covered scopes; ``allowed_groups`` is
    demoted from primary gate to post-grant filter.

    ``can_write``/``can_review`` honour both real grants (role ≥ editor/reviewer
    at a scope covering ``scope``) and the ``X-User-Roles`` header (back-compat
    so the default ``reviewer`` header keeps the existing suite green without
    seeding reviewer grants). When ``scope is None`` the grant check is "role
    at any scope" (a coarse gate).

    ``app`` principal grants (M6 service identities) are matched on
    ``principal_kind='app'`` + the app slug (``principal.user_id``) only — never
    against ``user``/``group`` grants, and never through the dev backdoor.
    """

    def __init__(self, session_factory=None) -> None:
        # Optional callable returning a SQLAlchemy Session, used only by the
        # write/review checks (the Protocol gives them no session). Defaults to
        # the app's SessionLocal; tests inject sqlite_factory. allowed_item_ids
        # takes the request session directly and never uses this factory.
        self._session_factory = session_factory

    # ------------------------------------------------------------------
    # grant matching (shared by read + write paths)
    # ------------------------------------------------------------------

    @staticmethod
    def _matching_grants(principal, session):
        """Load grants matching the principal.

        ``user`` principals match ``user`` grants on ``principal.user_id`` and
        ``group`` grants on ``principal.groups ∪ {'public'}``. ``app`` principals
        (M6 service identities) match ``app`` grants on ``principal.user_id``
        (the app slug) — and nothing else.
        """
        from k7e_api.models import RoleGrant

        if getattr(principal, "kind", "user") == "app":
            return (
                session.execute(
                    select(RoleGrant).where(
                        RoleGrant.principal_kind == "app",
                        RoleGrant.principal_id == principal.user_id,
                    )
                )
                .scalars()
                .all()
            )

        # Grant matching deliberately does NOT use effective_groups(): the
        # implicit user:<id> self-group is an allowed_groups filter concept,
        # not a grantable principal (user grants already match on user_id).
        match_groups = set(principal.groups) | {"public"}
        return (
            session.execute(
                select(RoleGrant).where(
                    or_(
                        and_(
                            RoleGrant.principal_kind == "user",
                            RoleGrant.principal_id == principal.user_id,
                        ),
                        and_(
                            RoleGrant.principal_kind == "group",
                            RoleGrant.principal_id.in_(match_groups),
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )

    def _open_session(self):
        if self._session_factory is not None:
            return self._session_factory()
        from k7e_api.db import SessionLocal

        return SessionLocal()

    # ------------------------------------------------------------------
    # read path
    # ------------------------------------------------------------------

    def allowed_item_ids(self, principal, session) -> set[uuid.UUID]:
        from k7e_api.models import KnowledgeItem, Space

        effective = effective_groups(principal)

        # Step 1: matching grants; keep those whose role ≥ viewer (all four
        # roles satisfy read; the filter is defensive against unknown roles).
        grants = [
            grant
            for grant in self._matching_grants(principal, session)
            if role_at_least(grant.role, "viewer")
        ]

        # Step 2: expand scopes downward into covered org/space/project ids.
        org_ids: set[uuid.UUID] = set()
        space_ids: set[uuid.UUID] = set()
        project_ids: set[uuid.UUID] = set()
        for grant in grants:
            if grant.scope_kind == "org":
                org_ids.add(grant.scope_id)
            elif grant.scope_kind == "space":
                space_ids.add(grant.scope_id)
            elif grant.scope_kind == "project":
                project_ids.add(grant.scope_id)

        # Step 3: admit published items under any covered scope. An item is
        # admitted if ANY of its containment ids is covered — org coverage
        # subsumes its spaces/projects; a narrower grant admits via space_id or
        # project_id (items carry space_id, so a space grant covers its
        # projects' items too).
        rows = session.execute(
            select(
                KnowledgeItem.id,
                KnowledgeItem.slug,
                KnowledgeItem.type,
                KnowledgeItem.allowed_groups,
                KnowledgeItem.provenance,
                KnowledgeItem.org_id,
                KnowledgeItem.space_id,
                KnowledgeItem.project_id,
            )
            .where(KnowledgeItem.status == "published")
            .where(KnowledgeItem.current_version_id.is_not(None))
        ).all()

        def _admitted(row) -> bool:
            _iid, _slug, _type, _ag, _prov, o_id, s_id, p_id = row
            return (
                (o_id is not None and o_id in org_ids)
                or (s_id is not None and s_id in space_ids)
                or (p_id is not None and p_id in project_ids)
            )

        admitted = [row for row in rows if _admitted(row)]

        # Personal (owner-owned) spaces are private to their owner even if an
        # item's allowed_groups is null — a hard backstop so no ingest path can
        # leak by leaving the ACL unset. Team/org spaces are unaffected.
        personal_owner_by_space: dict[uuid.UUID, str] = dict(
            session.execute(
                select(Space.id, Space.owner_user_id).where(Space.owner_user_id.is_not(None))
            ).all()
        )

        def _personal_ok(s_id) -> bool:
            owner = personal_owner_by_space.get(s_id)
            return owner is None or owner == principal.user_id

        # Steps 4–5: allowed_groups override + derived most-restrictive
        # (lifted verbatim from GroupAuthorizationService). A source page
        # survives iff admitted AND its allowed_groups passes; a derived page
        # survives iff every provenance.source_pages slug resolves to a
        # surviving source (fail-safe: an unresolvable slug hides the page).
        def _source_visible(allowed_groups) -> bool:
            if not allowed_groups:  # None or [] → public
                return True
            return bool(set(allowed_groups) & effective)

        visible_source_slugs = {
            slug
            for (_id, slug, type_, ag, _prov, _o, _s, _p) in admitted
            if type_ == "source" and _source_visible(ag) and _personal_ok(_s)
        }

        allowed: set[uuid.UUID] = set()
        for iid, _slug, type_, ag, prov, _o, _s, _p in admitted:
            if not _personal_ok(_s):
                continue
            if type_ == "source":
                if _source_visible(ag):
                    allowed.add(iid)
            else:
                source_pages = (prov or {}).get("source_pages") or []
                if all(sp in visible_source_slugs for sp in source_pages):
                    allowed.add(iid)
        return allowed

    # ------------------------------------------------------------------
    # write / review path
    # ------------------------------------------------------------------

    def can_review(self, principal, scope: Scope | None = None) -> bool:
        # X-User-Roles back-compat: the default 'reviewer' header (and, in dev
        # env only, the 'dev' local user) keep the existing suite green without
        # seeding reviewer grants.
        from k7e_api.auth import _dev_backdoor  # lazy: avoid import cycle

        if "reviewer" in principal.roles or _dev_backdoor(principal):
            return True
        return self._has_grant_at_least(principal, "reviewer", scope)

    def can_write(self, principal, scope: Scope | None = None) -> bool:
        # X-User-Roles back-compat: editor/reviewer/admin (and, in dev env only,
        # the 'dev' local user) pass the write gate — reviewer/admin imply editor.
        from k7e_api.auth import _dev_backdoor  # lazy: avoid import cycle

        if (
            "editor" in principal.roles
            or "reviewer" in principal.roles
            or "admin" in principal.roles
            or _dev_backdoor(principal)
        ):
            return True
        return self._has_grant_at_least(principal, "editor", scope)

    def can_admin(self, principal, scope: Scope | None = None) -> bool:
        # X-User-Roles back-compat: an 'admin' header (and, in dev env only, the
        # 'dev' local user) pass the admin gate — mirrors can_write/can_review.
        from k7e_api.auth import _dev_backdoor  # lazy: avoid import cycle

        if "admin" in principal.roles or _dev_backdoor(principal):
            return True
        return self._has_grant_at_least(principal, "admin", scope)

    def _has_grant_at_least(self, principal, minimum: str, scope: Scope | None) -> bool:
        """True iff the principal holds a grant of role ≥ ``minimum`` at a
        scope covering ``scope`` (or at any scope when ``scope is None``).

        Fail-closed: if the grant store is unreadable (no DB wired in the
        active runtime, table missing, …) the check denies — the header
        back-compat above has already granted known reviewer/editor/dev
        callers, so this only affects callers with no header role, for whom
        deny is the safe default. Authorization never fails open.
        """
        from sqlalchemy.exc import SQLAlchemyError

        session = self._open_session()
        try:
            grants = [
                grant
                for grant in self._matching_grants(principal, session)
                if role_at_least(grant.role, minimum)
            ]
            if scope is None:
                return len(grants) > 0
            return any(self._grant_covers_scope(grant, scope, session) for grant in grants)
        except SQLAlchemyError:
            # Grant store unreadable → fail-closed (deny). The header check
            # above already handled known roles/dev.
            return False
        finally:
            session.close()

    @staticmethod
    def _grant_covers_scope(grant, scope: Scope, session) -> bool:
        """True iff ``grant``'s scope is at or above ``scope`` (downward cover).

        org grant     → covers that org + its spaces + their projects.
        space grant   → covers that space + its projects.
        project grant → covers exactly that project.
        """
        from k7e_api.models import Project, Space

        if scope.kind == "org":
            return grant.scope_kind == "org" and grant.scope_id == scope.id
        if scope.kind == "space":
            if grant.scope_kind == "space":
                return grant.scope_id == scope.id
            if grant.scope_kind == "org":
                space = session.get(Space, scope.id)
                return space is not None and space.org_id == grant.scope_id
            return False  # a project grant cannot cover a whole space
        if scope.kind == "project":
            if grant.scope_kind == "project":
                return grant.scope_id == scope.id
            project = session.get(Project, scope.id)
            if project is None:
                return False
            if grant.scope_kind == "space":
                return project.space_id == grant.scope_id
            if grant.scope_kind == "org":
                space = session.get(Space, project.space_id)
                return space is not None and space.org_id == grant.scope_id
            return False
        return False
