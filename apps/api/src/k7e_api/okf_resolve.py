"""OKF ingest — pass 2a: resolve extraction into a link plan (deterministic, no LLM).

Turns the structured extraction into a list of page operations: which typed
pages to create vs update, and which ``[[wikilinks]]`` each should carry.
Matching against existing pages is by slug (exact); a fuzzy/embedding fallback
can be layered on later. Links are bidirectional — the source page links to each
entity/concept it informs, and each entity/concept links back to the source.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from k7e_api import okf
from k7e_api.okf_bundle import OkfBundle
from k7e_api.okf_extract import OkfExtraction


@dataclass
class PageOp:
    """One page to create or update, with its planned links + source facts."""

    page_type: str  # source | entity | concept
    slug: str
    title: str
    action: str  # create | update
    description: str = ""
    links: list[str] = field(default_factory=list)  # slugs to [[wikilink]]
    facts: list[str] = field(default_factory=list)  # facts to compose from
    aliases: list[str] = field(default_factory=list)  # alternate names for this page


def resolve(
    extraction: OkfExtraction,
    bundle: OkfBundle,
    *,
    source_slug: str,
    related_slugs: list[str] | None = None,
    aliases: dict[str, str] | None = None,
) -> list[PageOp]:
    """Build the ordered list of page operations (source page first).

    Args:
        related_slugs: existing-page slugs (from the graph-aware relate step) the
            source should also link to, weaving it into the existing graph.
        aliases: ``{extracted name: existing slug}`` — an extracted entity/concept
            that IS an existing page under another name. Reuse that page (update)
            instead of forking a duplicate.
    """
    existing = bundle.all_slugs()
    aliases = aliases or {}
    # All slugs already in the bundle, regardless of type. A KnowledgeItem is
    # keyed by slug alone, so we must not fork e.g. a concept "payment-retry-policy"
    # when a source of that slug exists — link to the existing page instead.
    existing_flat: set[str] = {s for slugs in existing.values() for s in slugs}
    ops: list[PageOp] = []
    child_slugs: list[str] = []
    planned: set[str] = set()  # slugs we are already creating an op for this run

    def _plan(page_type: str, name: str, description: str) -> None:
        # Dedup: if this name is an alias of an existing page, reuse that slug
        # (update the canonical page) instead of forking a new one.
        canonical = aliases.get(name)
        slug = canonical if canonical in existing_flat else okf.slugify(name)
        child_slugs.append(slug)  # the source links to it either way
        # Skip creating a page when the slug IS the source, is already planned,
        # or already exists under a *different* type — just link to it.
        if slug == source_slug or slug in planned:
            return
        if slug in existing_flat and slug not in existing[page_type]:
            return
        planned.add(slug)
        # Record the extracted name as an alias only when it truly differs from
        # the canonical slug (i.e. this was an alias-driven reuse, not the page's
        # own name).
        alias_names = (
            [name] if canonical in existing_flat and canonical != okf.slugify(name) else []
        )
        ops.append(
            PageOp(
                page_type=page_type,
                slug=slug,
                title=name,
                action="update" if slug in existing[page_type] else "create",
                description=description,
                links=[source_slug],
                facts=[description] if description else [],
                aliases=alias_names,
            )
        )

    for entity in extraction.entities:
        _plan("entity", entity.name, entity.description)
    for concept in extraction.concepts:
        _plan("concept", concept.name, concept.description)

    # References resolve to any existing page; the source links to them.
    ref_links: list[str] = []
    for ref in extraction.references:
        rslug = okf.slugify(ref)
        for page_type in ("concept", "entity", "source"):
            if rslug in existing[page_type]:
                ref_links.append(rslug)
                break

    # Graph-aware links to existing pages (validated: must exist, not the source).
    related_links = [s for s in (related_slugs or []) if s in existing_flat and s != source_slug]

    source_op = PageOp(
        page_type="source",
        slug=source_slug,
        title=extraction.title,
        action="update" if source_slug in existing["source"] else "create",
        description=extraction.summary,
        links=okf.dedupe(child_slugs + ref_links + related_links),
        facts=[extraction.summary] + [f"cites: {c}" for c in extraction.citations],
    )
    return [source_op, *ops]
