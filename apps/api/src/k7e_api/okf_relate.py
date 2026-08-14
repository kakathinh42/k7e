"""OKF ingest — link a new source into the EXISTING wiki graph, and de-duplicate.

``extract_okf`` reads one source in isolation, so it cannot know what pages
already exist — every upload becomes a weakly-connected island, and the same
real entity gets re-created under a different slug (e.g. ``Example Bank`` vs an
existing ``example-bank``). This step closes both gaps in one LLM call over the
existing-page catalog:

* ``related`` — existing pages the new source links to (joins the graph).
* ``aliases`` — the source's OWN entities/concepts that ARE an existing page
  (a translation or alternate name) → reuse that page instead of forking a dup.

LLM-based (no embeddings), so it works regardless of ``embeddings_enabled``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from k7e_api.llm_client import LLMClient
from k7e_api.logging_setup import get_logger
from k7e_api.okf_extract import OkfExtraction

logger = get_logger(__name__)

#: Cap how many existing pages we show the model per ingest. Beyond this the
#: catalog is truncated (logged here as `okf_catalog_truncated`); at large scale a pre-filter
#: (by tag/keyword overlap) should narrow the catalog before this call.
MAX_CATALOG = 150

RELATE_SYSTEM_PROMPT = (
    "You weave a new source document into an existing knowledge wiki. Given the "
    "new document and a catalog of existing wiki pages, return TWO things:\n"
    '1. "related": existing pages the document is directly about or closely '
    "related to (same entity, system, team, product, or concept). Be precise — "
    "never force a connection on a weak or generic overlap.\n"
    '2. "aliases": a map from one of THIS document\'s own entity/concept names '
    "to an existing page that is the SAME real thing under a different name "
    "(e.g. a translation, abbreviation, or alternate spelling). Only map exact "
    "same-entity matches, never merely-related ones.\n"
    'Return strict JSON: {"related": ["slug"], "aliases": {"name": "slug"}} '
    "using only slugs from the catalog (empty when nothing applies)."
)


def build_relate_prompt(extraction: OkfExtraction, catalog: list[tuple[str, str]]) -> str:
    names = [e.name for e in extraction.entities] + [c.name for c in extraction.concepts]
    catalog_block = "\n".join(f"  {slug}: {title}" for slug, title in catalog)
    return (
        f"New document title: {extraction.title}\n"
        f"Summary: {extraction.summary}\n"
        f"This document's entities/concepts: {', '.join(names) or '(none)'}\n\n"
        f"Existing wiki pages (slug: title):\n{catalog_block}\n\n"
        '1. Which existing pages does this document relate to? -> "related".\n'
        "2. Which of this document's entities/concepts ARE one of the existing "
        'pages under another name? -> "aliases" (name -> existing slug).\n'
        'Return JSON {"related": [...], "aliases": {...}}.'
    )


@dataclass
class RelateResult:
    """Graph-aware linking + dedup hints, validated against the catalog."""

    related: list[str] = field(default_factory=list)  # existing slugs to link
    aliases: dict[str, str] = field(default_factory=dict)  # extracted name -> slug


async def relate_existing(
    client: LLMClient,
    extraction: OkfExtraction,
    catalog: dict[str, str],
    *,
    max_catalog: int = MAX_CATALOG,
) -> RelateResult:
    """Return validated ``related`` links + ``aliases`` for the new source.

    Args:
        catalog: ``{slug: title}`` of existing pages (excluding this source).
    """
    if not catalog:
        return RelateResult()
    all_items = list(catalog.items())
    if len(all_items) > max_catalog:
        logger.warning("okf_catalog_truncated", total=len(all_items), used=max_catalog)
    items = all_items[:max_catalog]
    raw = await client.complete_json(
        system=RELATE_SYSTEM_PROMPT,
        user=build_relate_prompt(extraction, items),
        schema_name="OkfRelate",
    )
    known = {slug for slug, _ in items}

    # related: validate against the catalog, preserve order, dedupe.
    seen: set[str] = set()
    related: list[str] = []
    for slug in raw.get("related") or []:
        if isinstance(slug, str) and slug in known and slug not in seen:
            seen.add(slug)
            related.append(slug)

    # aliases: keep only name -> existing-slug entries that point into the catalog.
    aliases: dict[str, str] = {}
    raw_aliases = raw.get("aliases") or {}
    if isinstance(raw_aliases, dict):
        for name, slug in raw_aliases.items():
            if isinstance(name, str) and isinstance(slug, str) and slug in known:
                aliases[name] = slug

    return RelateResult(related=related, aliases=aliases)
