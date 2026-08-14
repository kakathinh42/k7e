"""Ingest router: handles manual file upload ingestion.

Endpoint:
    POST /upload
        - Validates file MIME type, filename, and size.
        - Stores file bytes in the object store.
        - Creates or reuses a Source row and inserts a RawDocument row.
        - Starts the ingest Temporal workflow via the injectable seam.
        - Increments the INGEST_TOTAL Prometheus counter.
        - Returns UploadResponse(workflow_id, raw_document_id).
"""

from __future__ import annotations

import hashlib
import inspect
from collections.abc import Awaitable
from datetime import datetime, timedelta, timezone
from typing import Annotated, Callable, Union

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import extract, func, select
from sqlalchemy.orm import Session

from k7e_api.app_auth import app_principal, get_app, get_effective_principal
from k7e_api.auth import (
    AuthorizationService,
    Principal,
    Scope,
    get_authz,
    require_verified_identity,
)
from k7e_api.config import get_settings
from k7e_api.connectors.base import FetchedDocument
from k7e_api.db import get_session
from k7e_api.deps import get_object_store, get_workflow_starter
from k7e_api.extraction import ExtractionError, pdf_page_count
from k7e_api.ingest_service import as_sync_workflow_starter, ingest_document
from k7e_api.metrics import INGEST_TOTAL
from k7e_api.models import (
    ClientApp,
    IngestRun,
    KnowledgeItem,
    RawDocument,
    Source,
    Space,
    Team,
    WikiChunk,
)
from k7e_api.object_store import ObjectStore
from k7e_api.personal_spaces import provision_personal_space
from k7e_api.schemas import (
    SourceIngestRequest,
    SourceIngestResponse,
    SpaceRef,
    UploadResponse,
)
from k7e_api.source_tier import resolve_source_tier
from k7e_api.spaces import space_refs_for
from k7e_api.teams import is_team_member
from k7e_api.tenancy import TenantContext, get_tenant_context
from k7e_api.validation import validate_upload

router = APIRouter()


# ---------------------------------------------------------------------------
# Space-targeted upload helpers (reused by POST /upload and POST /conversation)
# ---------------------------------------------------------------------------


def _resolve_target_space(
    session: Session,
    *,
    space_slug: str,
    principal: Principal,
    ctx: TenantContext,
    settings,
) -> Space:
    """Resolve the ``space`` field to a Space row.

    ``"personal"`` JIT-provisions (or returns) the caller's own personal
    space — gated by ``require_verified_identity`` so an unverified header
    caller can't ingest into someone else's identity outside dev env. Any
    other slug is an org-scoped lookup; unknown slugs 404 (filtering/ingest
    never auto-creates a non-personal space).
    """
    if space_slug == "personal":
        require_verified_identity(principal, settings)
        return provision_personal_space(session, user_id=principal.user_id, org_id=ctx.org_id)
    space = session.execute(
        select(Space).where(Space.org_id == ctx.org_id, Space.slug == space_slug)
    ).scalar_one_or_none()
    if space is None:
        raise HTTPException(status_code=404, detail="Space not found")
    return space


def _check_personal_cap(session: Session, *, space: Space, user_id: str, settings) -> None:
    """429 once a personal space's owner exceeds the daily ingest cap.

    Team/org spaces (``owner_user_id is None``) are uncapped.
    """
    if space.owner_user_id is None:
        return
    since = datetime.now(timezone.utc) - timedelta(days=1)
    count = session.execute(
        select(func.count(RawDocument.id)).where(
            RawDocument.space_id == space.id,
            RawDocument.created_by == user_id,
            RawDocument.created_at >= since,
        )
    ).scalar_one()
    if count >= settings.personal_ingest_daily_cap:
        raise HTTPException(
            status_code=429,
            detail=f"Personal ingest cap reached ({settings.personal_ingest_daily_cap}/day)",
        )


class IngestRunOut(BaseModel):
    """One row of the upload history: a compiled source's token + cost usage."""

    id: str
    raw_document_id: str | None
    filename: str
    source_slug: str | None
    model_id: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    llm_calls: int
    cost_usd: float
    page_count: int
    created_at: datetime
    # Which space this upload landed in (private / team / public), resolved via
    # its RawDocument. None for legacy runs or runs whose raw document was deleted.
    space: SpaceRef | None = None


@router.get("/history", response_model=list[IngestRunOut])
def ingest_history(
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[IngestRunOut]:
    """Recent uploads with their token usage and estimated $ cost (newest first)."""
    rows = (
        session.execute(select(IngestRun).order_by(IngestRun.created_at.desc()).limit(limit))
        .scalars()
        .all()
    )
    # Resolve each run's target space (via its RawDocument) so the History page
    # can filter by space kind. One query for the raw→space map, one (batched)
    # for the space classification.
    raw_ids = [r.raw_document_id for r in rows if r.raw_document_id]
    space_by_raw: dict = {}
    if raw_ids:
        space_by_raw = dict(
            session.execute(
                select(RawDocument.id, RawDocument.space_id).where(RawDocument.id.in_(raw_ids))
            ).all()
        )
    space_refs = space_refs_for(list(space_by_raw.values()), session)

    def _space_for(run: IngestRun) -> SpaceRef | None:
        space_id = space_by_raw.get(run.raw_document_id)
        ref = space_refs.get(space_id) if space_id else None
        return SpaceRef(**ref) if ref else None

    return [
        IngestRunOut(
            id=str(r.id),
            raw_document_id=str(r.raw_document_id) if r.raw_document_id else None,
            filename=r.filename,
            source_slug=r.source_slug,
            model_id=r.model_id,
            prompt_tokens=r.prompt_tokens,
            completion_tokens=r.completion_tokens,
            total_tokens=r.total_tokens,
            llm_calls=r.llm_calls,
            cost_usd=r.cost_usd,
            page_count=r.page_count,
            created_at=r.created_at,
            space=_space_for(r),
        )
        for r in rows
    ]


class EmbeddingStatusOut(BaseModel):
    """Corpus-wide embedding progress for the chunk index."""

    total: int
    embedded: int
    pending: int


@router.get("/embedding-status", response_model=EmbeddingStatusOut)
def embedding_status(
    session: Annotated[Session, Depends(get_session)],
    space_kind: Annotated[
        str | None,
        Query(description="Scope to a space kind: personal | team | public"),
    ] = None,
    year: Annotated[int | None, Query(description="Scope to this calendar year")] = None,
    month: Annotated[
        int | None, Query(ge=1, le=12, description="Scope to this month (1–12)")
    ] = None,
) -> EmbeddingStatusOut:
    """Chunk embedding progress, optionally scoped to the History page filters.

    With no params this reports corpus-wide progress. ``space_kind`` narrows to
    chunks whose page lives in a space of that kind (private/team/public);
    ``year``/``month`` narrow by the chunk's creation date — so the History
    "Embeddings" card mirrors whatever the table is currently filtered to.

    Embeddings are filled asynchronously by a backfill poll, so this reports how
    many chunks are embedded vs. still pending (``embedding IS NULL``) — surfacing
    a failed/stalled embedding.
    """

    def _scoped(stmt):
        """Apply the space-kind + date filters to a WikiChunk count statement."""
        stmt = stmt.select_from(WikiChunk)
        if space_kind in ("personal", "team", "public"):
            team_spaces = select(Team.space_id)
            stmt = stmt.join(KnowledgeItem, KnowledgeItem.id == WikiChunk.item_id).join(
                Space, Space.id == KnowledgeItem.space_id
            )
            if space_kind == "personal":
                stmt = stmt.where(Space.owner_user_id.is_not(None))
            elif space_kind == "team":
                stmt = stmt.where(Space.id.in_(team_spaces))
            else:  # public — shared org corpus (not personal, not team-owned)
                stmt = stmt.where(Space.owner_user_id.is_(None), Space.id.not_in(team_spaces))
        if year is not None:
            stmt = stmt.where(extract("year", WikiChunk.created_at) == year)
        if month is not None:
            stmt = stmt.where(extract("month", WikiChunk.created_at) == month)
        return stmt

    total = session.execute(_scoped(select(func.count()))).scalar_one()
    pending = session.execute(
        _scoped(select(func.count())).where(WikiChunk.embedding.is_(None))
    ).scalar_one()
    return EmbeddingStatusOut(total=total, embedded=total - pending, pending=pending)


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile,
    source_uri: Annotated[str, Form()] = "manual",
    source_system: Annotated[str, Form()] = "manual_upload",
    source_external_id: Annotated[str | None, Form()] = None,
    source_tier: Annotated[str | None, Form()] = None,
    allowed_groups: Annotated[str | None, Form()] = None,
    space: Annotated[str | None, Form()] = None,
    session: Annotated[Session, Depends(get_session)] = None,
    object_store: Annotated[ObjectStore, Depends(get_object_store)] = None,
    workflow_starter: Annotated[
        Callable[[str], Union[str, Awaitable[str]]], Depends(get_workflow_starter)
    ] = None,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)] = None,
    principal: Annotated[Principal, Depends(get_effective_principal)] = None,
    authz: Annotated[AuthorizationService, Depends(get_authz)] = None,
) -> UploadResponse:
    """Accept a file upload, persist it, and start the ingest workflow.

    A delegation-allowed ClientApp (``X-App-Key``) may upload on behalf of the
    end user it asserts via ``X-On-Behalf-Of-Email`` — the file is stamped and
    space-routed exactly as if that verified user called this endpoint
    directly (``get_effective_principal``), so ``space=personal`` provisions
    into *their* personal Space and the personal daily cap counts against
    them. Without the header pair, behavior is unchanged (falls through to
    the normal principal).

    Args:
        file: The uploaded file (multipart/form-data).
        source_uri: An optional string identifying the ingestion source.
                    Defaults to ``"manual"``.
        session: SQLAlchemy session (injected).
        object_store: Object store backend (injected).
        workflow_starter: Callable that starts the Temporal workflow (injected).
        ctx: Tenant context — used to stamp ``org_id`` on new rows (injected).
        space: Optional target space slug. ``"personal"`` JIT-provisions the
            caller's own space; any other slug is an org-scoped lookup (404 if
            absent). Omitted → today's legacy org-gated default bundle.

    Returns:
        UploadResponse with workflow_id and raw_document_id.

    Raises:
        HTTPException 403: If the caller is not an editor at the resolved scope,
            or a delegating app's on-behalf identity fails the domain guard.
        HTTPException 404: If ``space`` names an unknown non-personal slug.
        HTTPException 429: If a personal space's daily ingest cap is exceeded.
        HTTPException 400: If the file fails validation, or the on-behalf
            email is malformed.
    """
    # Resolve + write-gate the target space. Fail fast — before any file I/O
    # or row creation — so a rejected caller leaves no partial state behind.
    # No ``space`` field: today's org-gate path, byte-identical.
    target_space: Space | None = None
    if space is not None:
        settings = get_settings()
        target_space = _resolve_target_space(
            session, space_slug=space, principal=principal, ctx=ctx, settings=settings
        )
        # A personal space's owner is authorized by construction: the
        # "personal" alias just JIT-provisioned (and only flushed, not yet
        # committed) his editor/admin grants, so a cross-session grant walk
        # (rbac ``_open_session`` → a fresh SessionLocal) can't see them under
        # Postgres READ-COMMITTED and would 403 every verified personal upload.
        # ``require_verified_identity`` inside ``_resolve_target_space`` has
        # already vouched for the caller's identity — matching the plan's T8
        # personal branch, which gates personal purely on verified identity.
        # Team/org spaces (owner_user_id is None) and someone else's personal
        # slug fall through to the real grant walk, unchanged.
        is_owner = (
            target_space.owner_user_id is not None
            and target_space.owner_user_id == principal.user_id
        )
        if not is_owner and not authz.can_write(principal, Scope("space", target_space.id)):
            raise HTTPException(status_code=403, detail="Editor role required")
        _check_personal_cap(
            session, space=target_space, user_id=principal.user_id, settings=settings
        )
    elif not authz.can_write(principal, Scope("org", ctx.org_id)):
        raise HTTPException(status_code=403, detail="Editor role required")

    # 0. Resolve the source tier (explicit wins; else per-source-system default).
    try:
        resolved_tier = resolve_source_tier(source_system, source_tier)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 1. Read file bytes
    data = await file.read()

    # 2. Validate (raises ValueError on failure); count rejections in metrics
    try:
        validate_upload(file.filename or "", file.content_type or "", len(data))
    except ValueError as exc:
        INGEST_TOTAL.labels("manual", "rejected").inc()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 2b. PDFs: reject unreadable/oversized documents up front — before any
    #     storage or workflow start — so we never burn vision-LLM calls on a
    #     document we'd refuse to transcribe in full.
    extra_metadata: dict | None = None
    if file.content_type == "application/pdf":
        try:
            page_count = pdf_page_count(data)
        except ExtractionError as exc:
            INGEST_TOTAL.labels("manual", "rejected").inc()
            raise HTTPException(status_code=400, detail="unreadable pdf") from exc
        max_pages = get_settings().max_pdf_pages
        if page_count == 0 or page_count > max_pages:
            INGEST_TOTAL.labels("manual", "rejected").inc()
            raise HTTPException(
                status_code=400,
                detail=f"pdf must have between 1 and {max_pages} pages",
            )
        extra_metadata = {"page_count": page_count}

    # 3. Compute SHA-256 hex digest (64 chars — matches String(64) column)
    hex_digest = hashlib.sha256(data).hexdigest()  # 64-char lowercase hex

    # Ad-hoc/manual uploads carry no stable external id, so Tier-A source
    # identity (resolve_linked_item) can't dedup them and re-uploading the same
    # file forks a brand-new published page every time. Fall back to the content
    # hash as the external id: re-ingesting identical bytes then resolves to the
    # same KnowledgeItem, so the gate sees it as an update and routes it to
    # human review instead of auto-publishing a duplicate.
    if not source_external_id:
        source_external_id = hex_digest

    # 4. Store bytes in object store
    object_key = f"raw/manual/{hex_digest}.bin"
    object_store_ref = object_store.put(object_key, data)

    # 5. Ensure Source row exists (kind/name = source_uri)
    source = session.execute(select(Source).where(Source.name == source_uri)).scalar_one_or_none()
    if source is None:
        source = Source(
            name=source_uri,
            org_id=ctx.org_id if ctx is not None else None,
        )
        session.add(source)
        session.flush()  # Populate source.id without committing

    # 6. Insert RawDocument row, stamped with the tenant's org_id.
    # Personal spaces are not shareable in v1: force the item to the owner's
    # own self-group, overriding any form-supplied allowed_groups CSV.
    resolved_allowed_groups = (
        [f"user:{principal.user_id}"]
        if target_space is not None and target_space.owner_user_id is not None
        else (
            [g.strip() for g in allowed_groups.split(",") if g.strip()] if allowed_groups else None
        )
    )
    raw_document = RawDocument(
        filename=file.filename or "",
        sha256=hex_digest,
        object_store_ref=object_store_ref,
        mime_type=file.content_type or "",
        size_bytes=len(data),
        status="received",
        source_id=source.id,
        source_system=source_system,
        source_external_id=source_external_id,
        source_tier=resolved_tier,
        allowed_groups=resolved_allowed_groups,
        space_id=target_space.id if target_space is not None else None,
        created_by=principal.user_id,
        org_id=ctx.org_id if ctx is not None else None,
        extra_metadata=extra_metadata,
    )
    session.add(raw_document)
    session.flush()  # Populate raw_document.id
    session.commit()

    # 7. Start ingest workflow. The document row is already committed (so the
    #    worker can read it); if the start fails, mark the doc failed so it is
    #    not silently stuck, and surface a 503.
    try:
        result = workflow_starter(str(raw_document.id))
        if inspect.isawaitable(result):
            workflow_id = await result
        else:
            workflow_id = result
    except Exception as exc:
        raw_document.status = "failed"
        session.commit()
        INGEST_TOTAL.labels("manual", "failed").inc()
        raise HTTPException(status_code=503, detail="failed to start ingest workflow") from exc

    # 7b. Persist the workflow_id so the client can re-attach after a page
    #     refresh without losing track of the in-progress job.
    raw_document.workflow_id = workflow_id
    session.commit()

    # 8. Increment Prometheus counter
    INGEST_TOTAL.labels("manual", "accepted").inc()

    # 9. Return response
    return UploadResponse(
        workflow_id=workflow_id,
        raw_document_id=raw_document.id,
    )


# ---------------------------------------------------------------------------
# Status endpoint — lets the frontend re-attach to a job after page refresh
# ---------------------------------------------------------------------------


class IngestStatusOut(BaseModel):
    """Current status of an ingest job, queryable by raw_document_id."""

    raw_document_id: str
    status: str  # received | processing | done | failed
    workflow_id: str | None


@router.get("/status/{raw_document_id}", response_model=IngestStatusOut)
def ingest_status(
    raw_document_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> IngestStatusOut:
    """Return the current ingest status + workflow_id for a raw document.

    The pipeline runs as an async Temporal workflow and does not write back to
    ``raw_documents.status`` (it stays ``"received"``), so status is *derived*:

    - ``failed`` — a synchronous upload-time rejection already stamped the row
      (e.g. validation), OR the compile never produced output (see below);
    - ``done`` — an ``IngestRun`` exists for this document: ``okf_ingest``
      recorded its token/cost usage, i.e. the pages compiled and committed;
    - ``processing`` — otherwise (the workflow is still running).

    Returns 404 if the document does not exist.
    """
    import uuid as _uuid

    try:
        doc_uuid = _uuid.UUID(raw_document_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid raw_document_id") from exc

    doc = session.get(RawDocument, doc_uuid)
    if doc is None:
        raise HTTPException(status_code=404, detail="raw document not found")

    if doc.status == "failed":
        status = "failed"
    else:
        compiled = session.execute(
            select(IngestRun.id).where(IngestRun.raw_document_id == doc.id).limit(1)
        ).first()
        status = "done" if compiled is not None else "processing"

    return IngestStatusOut(
        raw_document_id=str(doc.id),
        status=status,
        workflow_id=doc.workflow_id,
    )


# ---------------------------------------------------------------------------
# Source ingest endpoint — a registered app ingests a text source as itself
# (M6 service identity, consumer-agnostic path used e.g. by chat-agent)
# ---------------------------------------------------------------------------


@router.post("/source", response_model=SourceIngestResponse)
def ingest_source(
    body: SourceIngestRequest,
    session: Annotated[Session, Depends(get_session)],
    app: Annotated[ClientApp, Depends(get_app)],
    authz: Annotated[AuthorizationService, Depends(get_authz)],
    object_store: Annotated[object, Depends(get_object_store)],
    workflow_starter: Annotated[object, Depends(get_workflow_starter)],
) -> SourceIngestResponse:
    """Ingest a text source as the authenticated app (service identity)."""
    principal = app_principal(app)
    if not authz.can_write(principal, Scope("org", app.org_id)):
        raise HTTPException(status_code=403, detail="Editor role required")
    if not body.content:
        raise HTTPException(status_code=400, detail="content must not be empty")

    # Validate the caller-supplied tier (this is the first ingest path where an
    # external, untrusted consumer sets source_tier as free JSON): an invalid
    # value must be a clean 400, not an unhandled DB error. Mirrors /upload.
    try:
        resolved_tier = resolve_source_tier(body.source_system, body.source_tier)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    doc = FetchedDocument(
        source_system=body.source_system,
        source_external_id=body.source_external_id,
        source_tier=resolved_tier,
        filename=body.source_external_id,
        content=body.content.encode("utf-8"),
        content_type=body.content_type,
    )
    result = ingest_document(
        session,
        object_store,
        as_sync_workflow_starter(workflow_starter),
        doc,
        org_id=app.org_id,
        allowed_groups=body.allowed_groups,
    )
    if result["status"] == "skipped":
        return SourceIngestResponse(status="skipped", raw_document_id="")
    return SourceIngestResponse(
        status="ingested",
        raw_document_id=result["raw_document_id"],
        workflow_id=result.get("workflow_id"),
    )


# ---------------------------------------------------------------------------
# Conversation ingest — chat-agent pushes a saved thread into its team Space
# (M3 Step C: a Tier-B, team-membership-gated shape over the generic ingest path)
# ---------------------------------------------------------------------------


class ConversationIngestIn(BaseModel):
    """A chat-agent conversation thread saved to a team's or the caller's own Space."""

    team: str | None = None  # team slug within the caller's org; absent -> personal
    source_external_id: str = Field(min_length=1, max_length=256)  # thread id
    content: str = Field(min_length=1, max_length=500_000)  # serialized transcript
    participants: list[str] = Field(default_factory=list)
    captured_at: datetime


class ConversationIngestOut(BaseModel):
    raw_document_id: str
    workflow_id: str | None
    idempotent: bool  # True when an unchanged thread was re-pushed (no-op)


@router.post("/conversation", response_model=ConversationIngestOut)
def ingest_conversation(
    body: ConversationIngestIn,
    session: Annotated[Session, Depends(get_session)],
    object_store: Annotated[ObjectStore, Depends(get_object_store)],
    workflow_starter: Annotated[object, Depends(get_workflow_starter)],
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    principal: Annotated[Principal, Depends(get_effective_principal)],
) -> ConversationIngestOut:
    """Ingest a chat-agent conversation thread into a team Space or the caller's
    own personal Space (Tier-B).

    ``team`` present: the existing team path — authorizes team membership (only
    a team's own members push into its private Space). ``team`` absent: the
    thread lands in the caller's personal Space, JIT-provisioned via the same
    ``"personal"`` alias the upload endpoint uses. The personal branch takes NO
    ``can_write`` check: the caller is authorized by construction (verified
    identity + it's his own space), exactly like the upload endpoint's owner
    path — see the comment there for why a grant-walk check would 403 under
    Postgres (flushed-not-committed grants invisible to a separate connection).
    Wraps the transcript as a Tier-B ``chat_agent`` source and starts the
    existing IngestWorkflow. Idempotent on (source_system, thread id, hash).
    """
    if body.team is not None:
        # Resolve the team within the caller's org; 404 if absent (don't cross orgs).
        team = session.execute(
            select(Team).where(Team.org_id == ctx.org_id, Team.slug == body.team)
        ).scalar_one_or_none()
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")

        # Membership is the write gate. Fail-closed: an anonymous/non-member
        # caller has no Membership row, so this denies before any object-store
        # or DB write.
        if not is_team_member(session, team.id, principal.user_id):
            raise HTTPException(status_code=403, detail="Team membership required")

        allowed_groups = [f"team:{team.slug}"]
        space_id = None
    else:
        settings = get_settings()
        target = _resolve_target_space(
            session,
            space_slug="personal",
            principal=principal,
            ctx=ctx,
            settings=settings,
        )
        _check_personal_cap(session, space=target, user_id=principal.user_id, settings=settings)
        allowed_groups = [f"user:{principal.user_id}"]
        space_id = target.id

    # Prepend a small provenance header so the compiler sees speaker/time context.
    header = (
        f"# Conversation thread {body.source_external_id}\n\n"
        f"- Participants: {', '.join(body.participants) or 'unknown'}\n"
        f"- Captured at: {body.captured_at.isoformat()}\n\n---\n\n"
    )
    doc = FetchedDocument(
        source_system="chat_agent",
        source_external_id=body.source_external_id,
        source_tier="B",
        filename=f"conversation-{body.source_external_id}.md",
        content=(header + body.content).encode("utf-8"),
        content_type="text/markdown",
        extra_metadata={
            "kind": "conversation",
            "participants": body.participants,
            "captured_at": body.captured_at.isoformat(),
        },
    )
    result = ingest_document(
        session,
        object_store,
        as_sync_workflow_starter(workflow_starter),
        doc,
        org_id=ctx.org_id,
        allowed_groups=allowed_groups,
        space_id=space_id,
        created_by=principal.user_id,
    )
    return ConversationIngestOut(
        raw_document_id=result.get("raw_document_id", ""),
        workflow_id=result.get("workflow_id"),
        idempotent=result["status"] == "skipped",
    )
