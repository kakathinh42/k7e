"""v2 OKF ingest activities — the autonomous, unified ingest pipeline.

Every source (doc or conversation) flows through the same two activities:
``okf_ingest_activity`` runs the two-pass ingest into the git bundle, and
``okf_mirror_activity`` syncs the bundle into Postgres for search + graph. No
gate, no review, no Tier-A/B branch.

Space routing (Task 9): a source targeted at a Space (personal or team) is
ingested and mirrored into that space's own OKF bundle under
``okf_bundles_root/<space_slug>/`` — the privacy boundary for personal
content — instead of the shared default bundle at ``okf_bundle_path``. See
``_bundle_for``.
"""

from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path
from typing import Callable

from k7e_api.config import get_settings
from k7e_api.db import SessionLocal
from k7e_api.ingest_history import record_ingest_run
from k7e_api.llm_client import LiteLLMClient
from k7e_api.logging_setup import get_logger
from k7e_api.models import Space
from k7e_api.okf_bundle import OkfBundle
from k7e_api.okf_ingest import ingest_source
from k7e_api.okf_mirror import mirror_bundle
from temporalio import activity
from temporalio.exceptions import ApplicationError

session_factory = SessionLocal


def _build_llm_client():
    """Construct the LLM client from configuration.

    ``LLM_CLIENT_IMPL=stub`` selects the deterministic in-process
    :class:`StubLLMClient` (used by the offline demo so the pipeline runs with
    no gateway key); otherwise the production :class:`LiteLLMClient`.
    """
    import os

    impl = os.environ.get("LLM_CLIENT_IMPL", "litellm").lower()
    if impl == "stub":
        from k7e_api.llm_client import StubLLMClient

        return StubLLMClient()
    return LiteLLMClient()


def _build_embedding_client():
    """Construct the embedding client from configuration.

    ``EMBEDDING_CLIENT_IMPL=stub`` selects the deterministic
    :class:`StubEmbeddingClient` (offline demo); otherwise the production
    :class:`LiteLLMEmbeddingClient`.
    """
    import os

    impl = os.environ.get("EMBEDDING_CLIENT_IMPL", "litellm").lower()
    if impl == "stub":
        from k7e_api.embedding_client import StubEmbeddingClient

        return StubEmbeddingClient()
    from k7e_api.embedding_client import LiteLLMEmbeddingClient

    return LiteLLMEmbeddingClient()


llm_client_factory: Callable = _build_llm_client
embedding_client_factory: Callable = _build_embedding_client
logger = get_logger(__name__)


def _bundle_for(settings, space_slug: str | None) -> OkfBundle:
    """Resolve the OKF bundle for a source: per-space when space-routed.

    ``space_slug`` set (personal or team-targeted ingest) -> the space's own
    bundle under ``okf_bundles_root/<slug>/`` — pages from one space never
    land in another space's (or the default) bundle. ``None`` (legacy,
    unrouted ingest) -> the shared default bundle at ``okf_bundle_path``,
    byte-identical to pre-Task-9 behaviour.
    """
    if space_slug:
        return OkfBundle(str(Path(settings.okf_bundles_root) / space_slug))
    return OkfBundle(settings.okf_bundle_path)


def _resolve_default_space(session):
    """Resolve the default Space for the default org.

    Activities cannot use FastAPI dependencies, so we replicate the same logic
    as ``get_tenant_context`` (which is FastAPI-only): look up the org by the
    configured ``default_org_slug``, then find the ``engineering`` space under it.

    Returns ``None`` when the org or space is not found (pre-seed environments),
    in which case ``mirror_bundle`` is called without a space and no tenant
    columns are set — the same legacy behaviour as before Task 4.
    """
    from k7e_api.models import Organization
    from sqlalchemy import select

    settings = get_settings()
    org = session.execute(
        select(Organization).where(Organization.slug == settings.default_org_slug)
    ).scalar_one_or_none()
    if org is None:
        logger.warning("okf_mirror_default_org_not_found", slug=settings.default_org_slug)
        return None

    space = session.execute(
        select(Space).where(Space.org_id == org.id, Space.slug == "engineering")
    ).scalar_one_or_none()
    if space is None:
        logger.warning(
            "okf_mirror_default_space_not_found",
            org=settings.default_org_slug,
            space="engineering",
        )
    return space


@activity.defn
async def okf_ingest_activity(
    redacted_text: str,
    raw_document_id: str,
    source: dict | None = None,
    space_slug: str | None = None,
) -> dict:
    """Ingest one source into the OKF git bundle (extract -> resolve -> compose -> commit).

    ``space_slug`` (``None`` for a legacy/unrouted source) selects the
    per-space bundle via ``_bundle_for`` — see module docstring.
    """
    source = source or {}
    settings = get_settings()
    bundle = _bundle_for(settings, space_slug)
    client = llm_client_factory()
    result = await ingest_source(
        bundle,
        redacted_text,
        client=client,
        today=date.today().isoformat(),
        resource=source.get("source_uri"),
    )

    # Record token usage + estimated $ cost for the upload-history view.
    # Best-effort — accounting must never fail an otherwise-successful ingest.
    usage = getattr(client, "usage", None)
    if usage:
        try:
            with session_factory() as session:
                run = record_ingest_run(
                    session,
                    raw_document_id=raw_document_id,
                    source_slug=result["source_slug"],
                    page_count=len(result["pages"]),
                    usage=usage,
                    model_id=settings.wiki_model,
                    settings=settings,
                )
            result["tokens"] = run.total_tokens
            result["cost_usd"] = run.cost_usd
        except Exception as exc:  # noqa: BLE001 - accounting is not load-bearing
            logger.warning("ingest_usage_record_failed", error=str(exc))

    logger.info(
        "okf_ingested",
        source_slug=result["source_slug"],
        page_count=len(result["pages"]),
        commit=result["commit"],
        tokens=usage.get("total_tokens") if usage else None,
        cost_usd=result.get("cost_usd"),
        space_slug=space_slug,
    )
    return result


@activity.defn
async def okf_mirror_activity(space_id: str | None = None, space_slug: str | None = None) -> dict:
    """Mirror the whole OKF bundle into Postgres for search + graph (idempotent).

    ``space_id`` set (personal or team-targeted ingest): mirror that space's
    own bundle (``_bundle_for``) stamped with its ``org_id``/``space_id``. A
    set-but-unresolvable ``space_id`` (space deleted mid-ingest, or a bug) is a
    permanent failure raised **non-retryable** — mirroring the per-space bundle
    with ``space=None`` would write personal content with no tenant stamps,
    breaching the privacy boundary; re-ingest is the correct recovery.
    ``space_id is None`` (legacy/unrouted ingest): unchanged pre-Task-9
    behaviour — mirror the shared default bundle against the default org's
    ``engineering`` space via ``_resolve_default_space``.
    """
    settings = get_settings()
    with session_factory() as session:
        if space_id is not None:
            space = session.get(Space, uuid.UUID(space_id))
            if space is None:
                raise ApplicationError(
                    f"Space not found for space-routed mirror: {space_id}",
                    non_retryable=True,
                )
        else:
            space = _resolve_default_space(session)
        bundle = _bundle_for(settings, space_slug)
        result = await mirror_bundle(session, bundle, space=space)
    logger.info("okf_mirrored", **result)
    return result
