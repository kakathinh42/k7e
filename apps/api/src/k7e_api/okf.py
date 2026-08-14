"""Open Knowledge Format (OKF) page model — typed Markdown + frontmatter + links.

A page is a typed Markdown file (source / entity / concept / analysis) with OKF
YAML frontmatter (``type`` is the only required field) and a body that
cross-links to other pages via ``[[wikilinks]]``. This module serializes and
parses pages and knows the bundle's directory layout. It has no DB or LLM
dependency, so it is trivially unit-testable.
"""

from __future__ import annotations

import hashlib
import re
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

PageType = Literal["source", "entity", "concept", "analysis"]

#: page type -> bundle subdirectory
PAGE_DIRS: dict[str, str] = {
    "source": "sources",
    "entity": "entities",
    "concept": "concepts",
    "analysis": "analyses",
}

#: Governed classification vocabulary (M4). Single-valued, fixed in code.
#: Distinct from free-form ``tags``: a ``domain`` MUST be one of these or null.
Domain = Literal[
    "backend",
    "frontend",
    "infra",
    "data",
    "security",
    "product",
    "mobile",
    "ops",
    "docs",
]

DOMAINS: tuple[str, ...] = (
    "backend",
    "frontend",
    "infra",
    "data",
    "security",
    "product",
    "mobile",
    "ops",
    "docs",
)


def coerce_domain(value: str | None) -> str | None:
    """Return ``value`` (normalized) iff it is a governed domain, else ``None``.

    The enum is authoritative: an out-of-vocabulary or hallucinated domain
    becomes ``None`` (unclassified) rather than entering the store. Case- and
    whitespace-insensitive.
    """
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized if normalized in DOMAINS else None


class OkfFrontmatter(BaseModel):
    """OKF frontmatter. ``type`` is the only required field; extras are allowed."""

    model_config = ConfigDict(extra="allow")

    type: str
    title: str
    description: str = ""
    resource: str | None = None  # URL of the underlying resource, if any
    domain: str | None = None  # governed classification (see DOMAINS); null = unclassified
    tags: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)  # alternate names (Obsidian)
    timestamp: str | None = None  # deprecated: prefer created/updated
    created: str | None = None  # YYYY-MM-DD, first ingest
    updated: str | None = None  # YYYY-MM-DD, last touch
    sources: list[str] = Field(default_factory=list)  # [[wikilink]] strings


class OkfPage(BaseModel):
    """A typed OKF page: slug + frontmatter + Markdown body."""

    slug: str
    frontmatter: OkfFrontmatter
    body: str


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


def serialize(page: OkfPage) -> str:
    """Render a page to ``---\\nfrontmatter\\n---\\n\\nbody\\n`` Markdown."""
    data = page.frontmatter.model_dump(exclude_none=True)
    fm = yaml.safe_dump(
        data, sort_keys=False, allow_unicode=True, default_flow_style=False
    ).strip()
    return f"---\n{fm}\n---\n\n{page.body.strip()}\n"


def parse(text: str, slug: str = "") -> OkfPage:
    """Parse Markdown-with-frontmatter back into an :class:`OkfPage`."""
    match = _FRONTMATTER_RE.match(text.lstrip())
    if not match:
        raise ValueError("OKF page is missing its '--- frontmatter ---' block")
    data = yaml.safe_load(match.group(1)) or {}
    return OkfPage(
        slug=slug,
        frontmatter=OkfFrontmatter.model_validate(data),
        body=match.group(2).strip(),
    )


def page_path(page_type: str, slug: str) -> str:
    """Return the bundle-relative path for a page (e.g. ``concepts/hot-cache.md``)."""
    return f"{PAGE_DIRS[page_type]}/{slug}.md"


def wikilink(slug: str, alias: str | None = None) -> str:
    """Format an Obsidian-style ``[[slug]]`` / ``[[slug|alias]]`` link."""
    return f"[[{slug}|{alias}]]" if alias else f"[[{slug}]]"


def slugify(name: str) -> str:
    """Lowercase, hyphenated slug from a human name (Unicode-aware).

    Keeps Unicode letters/digits so non-Latin names (e.g. Japanese) get a real,
    distinct slug instead of all collapsing to ``"untitled"``. Names with no word
    characters at all fall back to a stable content hash so distinct such names
    still don't collide.
    """
    # ``\w`` on a ``str`` pattern is Unicode-aware in Python 3 (keeps CJK etc.).
    slug = re.sub(r"[^\w]+", "-", name.strip().lower()).replace("_", "-").strip("-")
    if slug:
        return slug
    if not name.strip():
        return "untitled"
    return f"page-{hashlib.md5(name.encode('utf-8')).hexdigest()[:8]}"


def dedupe(seq: list[str]) -> list[str]:
    """Return ``seq`` with duplicates removed, preserving first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in seq:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
