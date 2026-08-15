"""P3: mirror the OKF git bundle into Postgres for permission-aware search + graph.

The git bundle is canonical; Postgres is a derived index. Each OKF page becomes
a published ``KnowledgeItem`` + version + embedded chunks, and every
``[[wikilink]]`` becomes an explicit ``WikiLink`` edge — so the existing
``/search``, ``/items``, ``/graph`` and the MCP server serve the new OKF pages
unchanged, and the graph shows real authored links instead of similarity guesses.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from k7e_api.chunking import chunk_markdown
from k7e_api.logging_setup import get_logger
from k7e_api.models import (
    ItemTag,
    KnowledgeItem,
    KnowledgeItemVersion,
    RawDocument,
    Space,
    WikiChunk,
    WikiLink,
)
from k7e_api.okf import PAGE_DIRS, OkfPage, coerce_domain, slugify
from k7e_api.okf_bundle import OkfBundle
from k7e_api.wikilinks import extract_wikilink_targets

logger = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_tags(raw: list[str]) -> list[str]:
    """Trim, lowercase, drop empties, de-dupe (preserve first-seen order)."""
    seen: set[str] = set()
    out: list[str] = []
    for tag in raw:
        norm = tag.strip().lower()
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def _sync_item_tags(session, item, raw_tags: list[str], org_id) -> None:
    """Diff the item's ItemTag rows to match ``raw_tags`` (insert/delete only).

    Guarded so a re-mirror with unchanged tags emits no writes (steady-state
    re-mirrors stay read-mostly). Runs for every page — including content-
    unchanged ones — so existing pages backfill their tags on the next mirror.
    """
    desired = set(_normalize_tags(raw_tags))
    existing = {
        row.tag: row
        for row in session.execute(select(ItemTag).where(ItemTag.item_id == item.id))
        .scalars()
        .all()
    }
    for tag, row in existing.items():
        if tag not in desired:
            session.delete(row)
    for tag in desired:
        if tag not in existing:
            session.add(ItemTag(item_id=item.id, tag=tag, org_id=org_id))


def _store_chunks(session, *, item, version, body, org_id=None) -> None:
    """Replace a page's chunks with text-only rows (embedding=NULL).

    Embedding is filled asynchronously by the backfill workflow — persisting a
    page must never depend on the embedding gateway. Deletes the item's prior
    chunks first (a content change re-chunks; the backfill re-embeds).
    """
    texts = chunk_markdown(body)
    session.query(WikiChunk).filter(WikiChunk.item_id == item.id).delete(synchronize_session=False)
    for i, text in enumerate(texts):
        session.add(
            WikiChunk(
                item_id=item.id,
                version_id=version.id,
                chunk_index=i,
                chunk_text=text,
                embedding=None,
                org_id=org_id,
            )
        )


async def mirror_bundle(
    session: Session,
    bundle: OkfBundle,
    *,
    space: Optional[Space] = None,
    model_id: str = "okf-mirror",
) -> dict:
    """Sync every page in the bundle into Postgres. Returns counts.

    Pass 1 upserts changed pages as a published item+version and writes their
    chunk text (``embedding=NULL``; the scheduled backfill fills the vectors).
    Pass 2 rebuilds the explicit ``[[wikilink]]`` edges over the synced pages.
    Idempotent and incremental: an unchanged page is skipped (no new version, no
    re-chunk), so re-mirroring after another upload only touches the new/changed
    pages.

    Args:
        space: The Space this bundle belongs to. When provided, every written
            ``KnowledgeItem``, ``WikiChunk``, and ``WikiLink`` is stamped with
            ``org_id=space.org_id`` and ``space_id=space.id`` (items only).
            When ``None`` (legacy / unit-test path), no tenant columns are set.
    """
    # Extract tenant stamps from the space (None-safe for legacy callers)
    org_id = space.org_id if space is not None else None
    space_id = space.id if space is not None else None

    # Collect pages, de-duplicated by slug. OKF page identity is (type, slug),
    # but a KnowledgeItem is keyed by slug alone, so two pages with the same slug
    # in different type dirs (e.g. a source AND a concept "payment-retry-policy")
    # would otherwise collide into one item and double-write its version + links.
    # First-seen wins (PAGE_DIRS order: source > entity > concept > analysis).
    pages: list[OkfPage] = []
    seen_slugs: set[str] = set()
    slug_to_type: dict[str, str] = {}
    collisions: list[str] = []
    for page_type in PAGE_DIRS:
        for slug in bundle.list_pages(page_type):
            if slug in seen_slugs:
                collisions.append(f"{page_type}/{slug}")
                continue
            page = bundle.read_page(page_type, slug)
            if page is not None:
                pages.append(page)
                seen_slugs.add(slug)
                slug_to_type[slug] = page_type
    if collisions:
        logger.warning("okf_slug_collision", dropped=collisions)

    slug_to_item: dict[str, KnowledgeItem] = {}
    changed = 0

    # Items that already have at least one chunk — used so a content-unchanged
    # page that never embedded (e.g. a prior rate-limit) gets retried.
    items_with_chunks: set = set(
        session.execute(select(WikiChunk.item_id).distinct()).scalars().all()
    )

    # Pass 1: item + version + chunks per *changed* page.
    for page in pages:
        now = _now()
        page_type = slug_to_type[page.slug]
        item = session.execute(
            select(KnowledgeItem).where(KnowledgeItem.slug == page.slug)
        ).scalar_one_or_none()

        if item is None:
            item = KnowledgeItem(
                slug=page.slug,
                title=page.frontmatter.title,
                status="draft",
                type=page_type,
                created_at=now,
                updated_at=now,
                org_id=org_id,
                space_id=space_id,
            )
            session.add(item)
            session.flush()
        else:
            # Persist/correct the page type on EVERY mirror, BEFORE the
            # incremental-skip check below, so a re-mirror backfills the true
            # type of an unchanged legacy row that defaulted to 'source'.
            if item.type != page_type:
                logger.info(
                    "okf_type_corrected",
                    slug=page.slug,
                    old=item.type,
                    new=page_type,
                )
            item.type = page_type
            # Stamp tenant columns on existing rows too (idempotent backfill).
            if org_id is not None and item.org_id is None:
                item.org_id = org_id
            if space_id is not None and item.space_id is None:
                item.space_id = space_id

        # Persist the page's provenance (raw OKF frontmatter refs) on EVERY
        # mirror, BEFORE the skip check below, so a re-mirror backfills it for
        # unchanged rows. Pure frontmatter copy — no DB lookups here.
        new_provenance = {
            "resource": page.frontmatter.resource,
            "source_pages": list(
                dict.fromkeys(
                    slugify(t)
                    for s in page.frontmatter.sources
                    for t in extract_wikilink_targets(s)
                )
            ),
        }
        # JSON columns aren't mutation-tracked, so assigning an equal dict would
        # still emit an UPDATE on every re-mirror (the worker re-mirrors the whole
        # bundle per upload); guard to keep steady-state re-mirrors read-mostly.
        if item.provenance != new_provenance:
            item.provenance = new_provenance

        # Personal space: EVERY page (source AND derived) is private to the
        # owner via the hard allowed_groups filter — independent of the fragile
        # frontmatter.resource -> RawDocument.sha256 match (conversation pages
        # set resource to a thread-id, which never matches a sha256).
        # Otherwise, source pages inherit their RawDocument's allowed_groups
        # (matched by sha256 == frontmatter.resource); derived pages stay null
        # (filtered via provenance). Set before the skip check so re-mirrors
        # propagate changes.
        if space is not None and space.owner_user_id:
            new_allowed = [f"user:{space.owner_user_id}"]
            if item.allowed_groups != new_allowed:
                item.allowed_groups = new_allowed
        elif page_type == "source" and page.frontmatter.resource:
            raw = (
                session.execute(
                    select(RawDocument)
                    .where(RawDocument.sha256 == page.frontmatter.resource)
                    .order_by(RawDocument.created_at.desc())
                )
                .scalars()
                .first()
            )
            new_allowed = raw.allowed_groups if raw is not None else None
            if item.allowed_groups != new_allowed:
                item.allowed_groups = new_allowed

        # Promote classification (M4) on EVERY mirror, before the skip check, so
        # a re-mirror backfills unchanged rows. Guarded to stay read-mostly.
        new_domain = coerce_domain(page.frontmatter.domain)
        if item.domain != new_domain:
            item.domain = new_domain
        _sync_item_tags(session, item, page.frontmatter.tags, org_id)

        # Incremental: skip pages whose content is unchanged since the last
        # mirror — no new version, no re-embed (avoids re-embedding the whole
        # bundle on every upload, which rate-limits the embed endpoint).
        if item.current_version_id is not None:
            current = session.get(KnowledgeItemVersion, item.current_version_id)
            content_unchanged = (
                current is not None
                and current.markdown_body == page.body
                and current.title == page.frontmatter.title
            )
            if content_unchanged:
                # Re-chunk a page that was synced but never chunked (e.g. a prior
                # failure) even though its content is unchanged; otherwise it
                # stays unsearchable forever.
                if item.id not in items_with_chunks:
                    _store_chunks(
                        session,
                        item=item,
                        version=current,
                        body=page.body,
                        org_id=org_id,
                    )
                slug_to_item[page.slug] = item
                continue

        next_number = (
            session.execute(
                select(func.max(KnowledgeItemVersion.version_number)).where(
                    KnowledgeItemVersion.item_id == item.id
                )
            ).scalar_one_or_none()
            or 0
        ) + 1
        version = KnowledgeItemVersion(
            item_id=item.id,
            version_number=next_number,
            markdown_body=page.body,
            model_id=model_id,
            created_by="okf-mirror",
            status="published",
            title=page.frontmatter.title,
            created_at=now,
            citations=[],
        )
        session.add(version)
        session.flush()
        item.current_version_id = version.id
        item.status = "published"
        item.title = page.frontmatter.title
        item.updated_at = now
        changed += 1

        # Write chunk text (embedding=NULL); the backfill fills the vectors.
        _store_chunks(session, item=item, version=version, body=page.body, org_id=org_id)
        slug_to_item[page.slug] = item

    session.flush()

    # Pass 2: rebuild explicit [[wikilink]] edges over the synced pages.
    item_ids = [it.id for it in slug_to_item.values()]
    if item_ids:
        session.query(WikiLink).filter(
            WikiLink.origin == "explicit",
            or_(
                WikiLink.source_item_id.in_(item_ids),
                WikiLink.target_item_id.in_(item_ids),
            ),
        ).delete(synchronize_session=False)

    # Pre-resolve ALL wikilink target slugs in one bulk query instead of one
    # fallback query per unknown slug. Collect every slug targeted by any page
    # in this run, then resolve the ones not already in slug_to_item at once.
    all_target_slugs: set[str] = set()
    for page in pages:
        for raw_target in extract_wikilink_targets(page.body):
            all_target_slugs.add(slugify(raw_target))

    missing_slugs = all_target_slugs - set(slug_to_item.keys())
    if missing_slugs:
        extra_items = (
            session.execute(select(KnowledgeItem).where(KnowledgeItem.slug.in_(missing_slugs)))
            .scalars()
            .all()
        )
        for extra in extra_items:
            slug_to_item[extra.slug] = extra

    link_count = 0
    # Global dedup of (source, target) pairs guards the uq_wiki_link constraint
    # even if some upstream data still collides (belt-and-suspenders).
    inserted: set[tuple] = set()
    for page in pages:
        src = slug_to_item[page.slug]
        for raw_target in extract_wikilink_targets(page.body):
            target_slug = slugify(raw_target)
            tgt = slug_to_item.get(target_slug)
            if tgt is None or tgt.id == src.id:
                continue
            pair = (src.id, tgt.id)
            if pair in inserted:
                continue
            inserted.add(pair)
            session.add(
                WikiLink(
                    source_item_id=src.id,
                    target_item_id=tgt.id,
                    relation="related",
                    score=1.0,
                    origin="explicit",
                    org_id=org_id,
                )
            )
            link_count += 1

    session.commit()
    return {
        "pages": len(pages),
        "changed": changed,
        "links": link_count,
    }
