"""SQLAlchemy 2 declarative models for the k7e platform."""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from k7e_api.embedding_type import EmbeddingVector


def _utcnow() -> datetime:
    """Return the current UTC datetime (timezone-aware)."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Shared SQLAlchemy 2 declarative base."""


# ---------------------------------------------------------------------------
# Organization / Space / Project – the M1 multi-org tenant hierarchy
#
# Organization is the tenant root (one per company / team).
# Space belongs to an Organization (roughly maps to a knowledge domain).
# Project belongs to a Space (a finer-grained collection within a domain).
#
# These three tables have no FKs *into* existing tables yet — those land in
# Task 2 (org_id seam on tenant-scoped rows).
# ---------------------------------------------------------------------------


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    settings: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class Space(Base):
    __tablename__ = "spaces"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    default_language: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="en", default="en"
    )
    okf_bundle_ref: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    connector_config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # Phase 4
    review_policy: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # visibility: advisory label for the Space's sharing posture. ``members``
    # = members-only (no org-wide viewer grant; access governed by grants —
    # e.g. the team-group editor grant). ``org`` = org-wide readable. The
    # column is advisory; actual access is always resolved from RoleGrants.
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default="members", server_default="members"
    )
    # Personal space marker: set ⇒ this Space is one user's private space
    # (JIT-provisioned; owner gets direct editor+admin grants). One per user
    # per org (partial unique index in migration 0024).
    owner_user_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    __table_args__ = (
        UniqueConstraint("org_id", "slug", name="uq_space_org_slug"),
        Index(
            "uq_space_org_owner",
            "org_id",
            "owner_user_id",
            unique=True,
            postgresql_where=text("owner_user_id IS NOT NULL"),
            sqlite_where=text("owner_user_id IS NOT NULL"),
        ),
    )


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("spaces.id"), nullable=False, index=True
    )
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    __table_args__ = (UniqueConstraint("space_id", "slug", name="uq_project_space_slug"),)


# ---------------------------------------------------------------------------
# RoleGrant – a principal's role at a scope node (M2 hierarchical RBAC)
#
# Binds a principal (user|group|app) to a role (viewer|editor|reviewer|admin)
# at a scope node (org|space|project). Grants inherit downward (Org → Space →
# Project → Page). The polymorphic (scope_kind, scope_id) ref is FK-less on
# purpose — a single SQL FK can't point at three tables, and grants are seeded
# by trusted code, not arbitrary user input (referential integrity is enforced
# in application code: the resolver only reads live orgs/spaces/projects).
#
# NOTE: role_grants is deliberately NOT an org_id-scoped content table — a
# grant's tenant is implied by its scope — so it does not get an org_id column
# and does not pass through scoped(). `app` principal_kind is wired as of M6
# (service-identity ClientApps; matched by the RBAC resolver for app principals).
# ---------------------------------------------------------------------------


class RoleGrant(Base):
    """A principal's role at a scope node (org/space/project). Inherits downward.

    `scope_id` is FK-less polymorphic (discriminated by `scope_kind`); referential
    integrity is enforced in application code (the resolver only reads live
    orgs/spaces/projects). `role_grants` is NOT an org_id-scoped content table —
    a grant's tenant is implied by its scope — so it does not pass through scoped().
    `app` principal_kind is wired as of M6 (service-identity ClientApps).
    """

    __tablename__ = "role_grants"
    __table_args__ = (
        UniqueConstraint(
            "principal_kind",
            "principal_id",
            "role",
            "scope_kind",
            "scope_id",
            name="uq_role_grant",
        ),
        Index("ix_role_grant_principal", "principal_kind", "principal_id"),
        Index("ix_role_grant_scope", "scope_kind", "scope_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    principal_kind: Mapped[str] = mapped_column(String(16), nullable=False)  # user|group|app
    principal_id: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # viewer|editor|reviewer|admin
    scope_kind: Mapped[str] = mapped_column(String(16), nullable=False)  # org|space|project
    scope_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


# ---------------------------------------------------------------------------
# Team / Membership – M3 team-owned knowledge spaces
#
# A Team owns one Space (members-only by default) and a group editor grant on
# it; Memberships resolve the team:{slug} groups a principal gains. The owner
# additionally carries a user admin grant at the space (drives can_admin).
# ---------------------------------------------------------------------------


class Team(Base):
    """A managed member-group that owns a private knowledge Space.

    A Team composes the multi-org model: it owns one Space (``space_id``,
    unique) and a ``RoleGrant(group="team:{slug}", role="editor", scope=space)``
    so every member shares read+write. The creator is seeded as the ``owner``
    Membership + a ``user`` admin grant at the space (so ``can_admin`` passes).
    """

    __tablename__ = "teams"
    __table_args__ = (
        UniqueConstraint("org_id", "slug", name="uq_team_org_slug"),
        UniqueConstraint("space_id", name="uq_team_space"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("spaces.id"), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    created_by: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class Membership(Base):
    """A user's membership in a Team, with a role (owner|admin|member|viewer).

    Membership is the source of truth for "who is in the team":
    ``team_groups_for_user`` resolves the ``team:{slug}`` groups a principal
    gains from their Memberships. An owner/admin additionally carries a ``user``
    admin grant at the team space so ``can_admin`` admits them.
    """

    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("team_id", "user_id", name="uq_membership_team_user"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    role: Mapped[str] = mapped_column(
        String(32), nullable=False, default="member"
    )  # owner|admin|member|viewer
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


# ---------------------------------------------------------------------------
# User – a native email+password account (PAT SSO). Email IS the identity
# (Principal.user_id), consistent with the JWT/session seams; only the bcrypt
# password hash is stored. Registration is domain-gated (e.g. @example.com).
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


# ---------------------------------------------------------------------------
# PersonalAccessToken – a user-scoped long-lived credential (PAT SSO). The
# caller presents `Authorization: Bearer wpat_<token>`; only the sha256 hash is
# stored. Verifying it yields the owning user's identity (user_id = email).
# Revocable (revoked_at) with optional expiry; last_used_at for auditing.
# ---------------------------------------------------------------------------


class PersonalAccessToken(Base):
    __tablename__ = "personal_access_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# ClientApp – a registered consumer application (M6 first-class `app` principal)
#
# A ClientApp authenticates via an X-App-Key (only the sha256 hash is stored)
# and acts as a service identity: its permissions come from
# RoleGrant(principal_kind="app", principal_id=<slug>). Distinct from the
# end-user identity M7 forwards via JWT.
# ---------------------------------------------------------------------------


class ClientApp(Base):
    __tablename__ = "client_apps"
    __table_args__ = (
        UniqueConstraint("org_id", "slug", name="uq_client_app_org_slug"),
        Index("ix_client_apps_api_key_hash", "api_key_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Delegated identity (trusted subsystem): when true, this app may act on
    # behalf of an end user by sending X-On-Behalf-Of-Email. Off by default —
    # only explicitly-trusted apps (e.g. chat-agent) get it.
    can_delegate_identity: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # Optional guard: restrict which email domain this app may assert (e.g.
    # "example.com"). NULL = no domain restriction.
    allowed_identity_domain: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


# ---------------------------------------------------------------------------
# Source – an ingestion source (e.g. a Confluence space, a file share)
# ---------------------------------------------------------------------------


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Task 2: tenant seam — org this source belongs to (nullable in ORM; NOT NULL
    # enforced by migration 0016 after backfill)
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("organizations.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extra_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    # relationships
    raw_documents: Mapped[list["RawDocument"]] = relationship(
        "RawDocument", back_populates="source"
    )


# ---------------------------------------------------------------------------
# RawDocument – a single uploaded / ingested file
# ---------------------------------------------------------------------------


class RawDocument(Base):
    __tablename__ = "raw_documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Task 2: tenant seam — org this document belongs to (nullable in ORM; NOT NULL
    # enforced by migration 0016 after backfill)
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("organizations.id"), nullable=True, index=True
    )
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    object_store_ref: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    extra_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    # status: pending | processing | done | failed
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    # source identity (Phase 2): how this raw doc maps to a wiki page
    source_system: Mapped[str] = mapped_column(String(64), nullable=False, default="manual_upload")
    source_external_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    # source_tier: 'A' authoritative/page-like | 'B' conversational/signal
    source_tier: Mapped[str] = mapped_column(String(1), nullable=False, default="A")
    authority_weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    # allowed_groups: upload-time access restriction (null/[] = public),
    # propagated onto the source page at mirror time.
    allowed_groups: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # Target space for space-routed ingestion (NULL = legacy default bundle).
    space_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("spaces.id"), nullable=True, index=True
    )
    # Uploader identity (JWT sub / header user) — provenance + personal cap.
    created_by: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    # workflow_id: the Temporal workflow run that processes this document.
    # Stored so the status can be re-queried after a page refresh.
    workflow_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    # relationships
    source: Mapped[Optional["Source"]] = relationship("Source", back_populates="raw_documents")
    knowledge_item_versions: Mapped[list["KnowledgeItemVersion"]] = relationship(
        "KnowledgeItemVersion", back_populates="raw_document"
    )


# ---------------------------------------------------------------------------
# KnowledgeItem – a compiled, versioned knowledge article
#
# Note: current_version_id has use_alter=True because it forms a circular FK
# with knowledge_item_versions.item_id.  The deferred ALTER TABLE constraint
# is emitted by Alembic; at Python import time no DB connection is needed.
# ---------------------------------------------------------------------------


class KnowledgeItem(Base):
    __tablename__ = "knowledge_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Task 2: tenant seam — org/space/project this item belongs to.
    # org_id and space_id are nullable in ORM; NOT NULL enforced by migration 0016
    # after backfill. project_id stays nullable (items may not belong to a project).
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("organizations.id"), nullable=True, index=True
    )
    space_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("spaces.id"), nullable=True, index=True
    )
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("projects.id"), nullable=True, index=True
    )
    slug: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    # status: draft | published | rejected. Indexed (migration 0018): every
    # read/search filters ``status == 'published'``.
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    # type: source | entity | concept | analysis (OKF page type; default-safe)
    type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="source", server_default="source"
    )
    # domain: governed single-valued classification (M4). Indexed; every facet
    # count + domain filter reads it. Nullable = unclassified. Values are
    # validated against okf.DOMAINS before persistence (see okf.coerce_domain).
    domain: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    # provenance: raw OKF refs {"resource": str|None, "source_pages": [slug]}
    provenance: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # allowed_groups: source-page access groups (null/[] = public). Derived
    # pages leave this null and are filtered via provenance.source_pages.
    allowed_groups: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # current_version_id: indexed (migration 0018) — every read joins the
    # current version row. use_alter=True because this forms a circular FK
    # with knowledge_item_versions.item_id; the deferred ALTER TABLE
    # constraint is emitted by Alembic. ``index=True`` is orthogonal to the
    # FK (the index is created directly; the FK constraint is deferred).
    current_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey(
            "knowledge_item_versions.id",
            use_alter=True,
            name="fk_ki_current_version_id",
        ),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    # relationships
    versions: Mapped[list["KnowledgeItemVersion"]] = relationship(
        "KnowledgeItemVersion",
        primaryjoin="KnowledgeItemVersion.item_id == KnowledgeItem.id",
        back_populates="item",
        cascade="all, delete-orphan",
    )
    current_version: Mapped[Optional["KnowledgeItemVersion"]] = relationship(
        "KnowledgeItemVersion",
        primaryjoin="KnowledgeItem.current_version_id == KnowledgeItemVersion.id",
        foreign_keys="[KnowledgeItem.current_version_id]",
        post_update=True,
    )


# ---------------------------------------------------------------------------
# ItemTag – one free-form tag on a KnowledgeItem (M4 queryable classification)
#
# Normalized (one row per (item, tag)) so tag filtering + facet counts are
# plain SQL joins / GROUP BY that behave identically on SQLite (tests) and
# Postgres (prod). Tags are derived from OKF frontmatter by the mirror; this
# table is a derived index, never authored directly.
# ---------------------------------------------------------------------------


class ItemTag(Base):
    __tablename__ = "item_tags"
    __table_args__ = (
        UniqueConstraint("item_id", "tag", name="uq_item_tag"),
        Index("ix_item_tags_tag", "tag"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # tenant seam — stamped from the item's org so tag facets can be org-scoped.
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("organizations.id"), nullable=True, index=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("knowledge_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tag: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


# ---------------------------------------------------------------------------
# KnowledgeItemVersion – an immutable point-in-time snapshot of an article
# ---------------------------------------------------------------------------


class KnowledgeItemVersion(Base):
    __tablename__ = "knowledge_item_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("knowledge_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    raw_document_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("raw_documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # status: draft | pending_review | published | rejected | superseded
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_review")
    # title snapshot for this version (lets the live item's title change only on publish/approve)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    markdown_body: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    # citations: list of {raw_document_id, quote} dicts
    citations: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    extra_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    # relationships
    item: Mapped["KnowledgeItem"] = relationship(
        "KnowledgeItem",
        primaryjoin="KnowledgeItemVersion.item_id == KnowledgeItem.id",
        foreign_keys="[KnowledgeItemVersion.item_id]",
        back_populates="versions",
    )
    raw_document: Mapped[Optional["RawDocument"]] = relationship(
        "RawDocument", back_populates="knowledge_item_versions"
    )
    gate_decisions: Mapped[list["GateDecision"]] = relationship(
        "GateDecision", back_populates="version", cascade="all, delete-orphan"
    )
    review_tasks: Mapped[list["ReviewTask"]] = relationship(
        "ReviewTask", back_populates="version", cascade="all, delete-orphan"
    )
    chunks: Mapped[list["WikiChunk"]] = relationship("WikiChunk", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# GateDecision – the outcome of the gate policy for a version
# ---------------------------------------------------------------------------


class GateDecision(Base):
    __tablename__ = "gate_decisions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Task 2: tenant seam (nullable in ORM; NOT NULL enforced by migration 0016)
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("organizations.id"), nullable=True, index=True
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("knowledge_item_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    # decision: publish | review | reject
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    reasons: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    has_redaction: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    # relationships
    version: Mapped["KnowledgeItemVersion"] = relationship(
        "KnowledgeItemVersion", back_populates="gate_decisions"
    )


# ---------------------------------------------------------------------------
# ReviewTask – a pending human-review assignment
# ---------------------------------------------------------------------------


class ReviewTask(Base):
    __tablename__ = "review_tasks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Task 2: tenant seam (nullable in ORM; NOT NULL enforced by migration 0016)
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("organizations.id"), nullable=True, index=True
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("knowledge_item_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    # status: pending | approved | rejected
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    assigned_to: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    decided_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    decision_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # relationships
    version: Mapped["KnowledgeItemVersion"] = relationship(
        "KnowledgeItemVersion", back_populates="review_tasks"
    )


# ---------------------------------------------------------------------------
# WikiChunk – a chunk of a KnowledgeItemVersion with its embedding vector
# ---------------------------------------------------------------------------


class WikiChunk(Base):
    __tablename__ = "wiki_chunks"
    __table_args__ = (
        # Supports the embedding-backfill poll, which runs
        # ``WHERE embedding IS NULL ORDER BY created_at, id LIMIT N`` every
        # ~2 min. Partial so it stays small once the backlog drains.
        Index(
            "ix_wiki_chunks_pending_embedding",
            "created_at",
            "id",
            postgresql_where=text("embedding IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Task 2: tenant seam (nullable in ORM; NOT NULL enforced by migration 0016)
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("organizations.id"), nullable=True, index=True
    )
    # item_id: indexed (migration 0018) — used by the mirror's chunk
    # delete/select by item and the ``ondelete="CASCADE"`` FK Postgres
    # services via it.
    item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("knowledge_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("knowledge_item_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Optional[list[Any]]] = mapped_column(EmbeddingVector, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


# ---------------------------------------------------------------------------
# SourcePageLink – deterministic identity: an external source -> a wiki page
# ---------------------------------------------------------------------------


class SourcePageLink(Base):
    __tablename__ = "source_page_links"
    __table_args__ = (
        UniqueConstraint("source_system", "source_external_id", name="uq_source_page_link"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Task 2: tenant seam (nullable in ORM; NOT NULL enforced by migration 0016)
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("organizations.id"), nullable=True, index=True
    )
    source_system: Mapped[str] = mapped_column(String(64), nullable=False)
    source_external_id: Mapped[str] = mapped_column(String(512), nullable=False)
    knowledge_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("knowledge_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


# ---------------------------------------------------------------------------
# Claim – an atomic, attributed fact mined from a conversational (Tier-B) source
# ---------------------------------------------------------------------------


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Task 2: tenant seam (nullable in ORM; NOT NULL enforced by migration 0016)
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("organizations.id"), nullable=True, index=True
    )
    raw_document_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("raw_documents.id", ondelete="SET NULL"), nullable=True
    )
    # The page this claim is proposed against, when known (else a new-stub
    # candidate). Nullable.
    linked_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("knowledge_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Near-duplicate claims (same fact across conversations) are grouped into a
    # ClaimCluster; the cluster's support_count = how many distinct conversations
    # corroborate the fact. Nullable until clustering runs.
    cluster_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("claim_clusters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    speaker: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # status: pending_review | approved | rejected
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_review")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class ClaimCluster(Base):
    """A group of near-duplicate claims (the same fact seen across conversations).

    ``support_count`` is the number of distinct source conversations that
    corroborate the fact — the corroboration signal the claims gate uses to
    decide auto-publish vs human review.
    """

    __tablename__ = "claim_clusters"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Task 2: tenant seam (nullable in ORM; NOT NULL enforced by migration 0016)
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("organizations.id"), nullable=True, index=True
    )
    canonical_text: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    # Embedding of the canonical (first) claim — new claims match against this.
    centroid: Mapped[list] = mapped_column(JSON, nullable=False)
    support_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # open | auto_accept | review | folded
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    folded_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("knowledge_item_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


# ---------------------------------------------------------------------------
# WikiLink – a typed page<->page edge (vector-similarity 'related' for now)
# ---------------------------------------------------------------------------


class WikiLink(Base):
    __tablename__ = "wiki_links"
    __table_args__ = (
        UniqueConstraint(
            "source_item_id",
            "target_item_id",
            "relation",
            "origin",
            name="uq_wiki_link",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Task 2: tenant seam (nullable in ORM; NOT NULL enforced by migration 0016)
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("organizations.id"), nullable=True, index=True
    )
    source_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("knowledge_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_items.id", ondelete="CASCADE"), nullable=False
    )
    relation: Mapped[str] = mapped_column(String(32), nullable=False, default="related")
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    origin: Mapped[str] = mapped_column(String(32), nullable=False, default="vector")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


# IngestRun – per-upload token usage + estimated $ cost of compiling a source.
# One row per okf ingest activity; powers the "upload history" view.
class IngestRun(Base):
    __tablename__ = "ingest_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Task 2: tenant seam (nullable in ORM; NOT NULL enforced by migration 0016)
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("organizations.id"), nullable=True, index=True
    )
    raw_document_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("raw_documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    source_slug: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
