"""OKF ingest orchestrator: one source -> typed, linked pages in the bundle.

Runs the two-pass hybrid end to end: extract (LLM) -> resolve (deterministic
link plan) -> compose (LLM body per page) -> write + index + log + git commit.
Fully autonomous: no gate, no review. Plain async so it is unit-testable with a
StubLLMClient; a Temporal activity is a thin wrapper around it.
"""

from __future__ import annotations

import re

from k7e_api import okf
from k7e_api.llm_client import LLMClient
from k7e_api.okf import PAGE_DIRS, OkfFrontmatter, OkfPage
from k7e_api.okf_bundle import OkfBundle
from k7e_api.okf_compose import compose_body
from k7e_api.okf_extract import extract_okf
from k7e_api.okf_relate import relate_existing
from k7e_api.okf_resolve import resolve


def _with_related(body: str, links: list[str]) -> str:
    """Append a deterministic ``## Related`` section so planned links are guaranteed."""
    links = okf.dedupe(links)
    if not links:
        return body.strip()
    related = "\n".join(f"- [[{slug}]]" for slug in links)
    return f"{body.strip()}\n\n## Related\n{related}\n"


_BODY_WIKILINK_RE = re.compile(r"\[\[\s*([^\[\]|]+?)\s*(?:\|([^\[\]]*))?\]\]")


def _sanitize_links(body: str, valid_slugs: set[str]) -> str:
    """De-dangle: strip inline ``[[wikilinks]]`` that don't resolve to a real page.

    The compose LLM sometimes invents links to pages that don't exist (e.g.
    ``[[用語集]]`` "glossary"). Replace any ``[[X]]`` whose slug isn't a known page
    with its plain text, so the rendered wiki carries no broken links.
    """

    def repl(m: "re.Match[str]") -> str:
        target, alias = m.group(1), m.group(2)
        if okf.slugify(target) in valid_slugs:
            return m.group(0)
        return (alias or target).strip()

    return _BODY_WIKILINK_RE.sub(repl, body)


def _existing_catalog(bundle: OkfBundle, *, exclude: str) -> dict[str, str]:
    """Return ``{slug: title}`` of existing pages (excluding ``exclude``)."""
    catalog: dict[str, str] = {}
    for page_type in PAGE_DIRS:
        for slug in bundle.list_pages(page_type):
            if slug == exclude:
                continue
            page = bundle.read_page(page_type, slug)
            if page is not None:
                catalog[slug] = page.frontmatter.title
    return catalog


def _merge_existing(page: OkfPage, existing: OkfPage, today: str) -> OkfPage:
    """On update: preserve earliest ``created`` + canonical title; union aliases.

    Returns a new ``OkfPage`` (does not mutate the input).
    """
    fm = page.frontmatter.model_copy()
    fm.created = existing.frontmatter.created or existing.frontmatter.timestamp or today
    fm.updated = today
    fm.aliases = okf.dedupe(list(existing.frontmatter.aliases) + list(fm.aliases))
    # Don't let an alias-driven update rename the canonical page.
    fm.title = existing.frontmatter.title or fm.title
    return OkfPage(slug=page.slug, frontmatter=fm, body=page.body)


async def ingest_source(
    bundle: OkfBundle,
    source_text: str,
    *,
    client: LLMClient,
    today: str,
    source_slug: str | None = None,
    resource: str | None = None,
) -> dict:
    """Ingest one source into the bundle. Returns a summary dict.

    Args:
        today: ISO date stamp (passed in — the orchestrator does no wall-clock).
    """
    bundle.init()
    extraction = await extract_okf(client, source_text)
    slug = source_slug or extraction.slug or okf.slugify(extraction.title)

    # Graph-aware: link the new source into existing pages (so it joins the graph
    # instead of forming an island) and reuse existing pages for same-entity
    # aliases (dedup). Best-effort — never fail ingest.
    related: list[str] = []
    aliases: dict[str, str] = {}
    try:
        catalog = _existing_catalog(bundle, exclude=slug)
        relate = await relate_existing(client, extraction, catalog)
        related, aliases = relate.related, relate.aliases
    except Exception:  # noqa: BLE001 - linking is additive, not load-bearing
        pass

    ops = resolve(
        extraction,
        bundle,
        source_slug=slug,
        related_slugs=related,
        aliases=aliases,
    )

    # Slugs that will exist after this ingest (used to strip invented inline links).
    valid_slugs: set[str] = {op.slug for op in ops}
    for slugs in bundle.all_slugs().values():
        valid_slugs |= slugs

    # Phase A (no lock): compose every body and build the OkfPage objects. This
    # holds no lock across the slow LLM calls.
    prepared: list[OkfPage] = []
    for op in ops:
        existing = bundle.read_page(op.page_type, op.slug)
        body = await compose_body(
            client,
            page_type=op.page_type,
            title=op.title,
            description=op.description,
            facts=op.facts,
            links=op.links,
            existing_body=existing.body if existing is not None else None,
        )
        body = _sanitize_links(body, valid_slugs)
        body = _with_related(body, op.links)
        frontmatter = OkfFrontmatter(
            type=op.page_type,
            title=op.title,
            description=op.description,
            tags=extraction.tags,
            domain=extraction.domain,
            aliases=list(op.aliases),
            created=today,
            updated=today,
            resource=resource if op.page_type == "source" else None,
            sources=[] if op.page_type == "source" else [okf.wikilink(slug)],
        )
        prepared.append(OkfPage(slug=op.slug, frontmatter=frontmatter, body=body))

    # Phase B (locked): re-merge cheap metadata, write, index, log, commit. Only
    # this fast critical section is serialized across concurrent ingests.
    written: list[str] = []
    created_slugs: list[str] = []
    updated_slugs: list[str] = []
    with bundle.lock():
        for page in prepared:
            existing = bundle.read_page(page.frontmatter.type, page.slug)
            if existing is not None:
                page = _merge_existing(page, existing, today)
                updated_slugs.append(page.slug)
            else:
                created_slugs.append(page.slug)
            bundle.write_page(page)
            written.append(okf.page_path(page.frontmatter.type, page.slug))
        bundle.update_index()
        bundle.append_log_entry(
            op="ingest",
            subject=slug,
            created=created_slugs,
            updated=updated_slugs,
            timestamp=today,
        )
        commit = bundle.commit(
            f"ingest: {slug} (+{len(created_slugs)} new, ~{len(updated_slugs)} updated)"
        )

    return {"source_slug": slug, "pages": written, "commit": commit}
