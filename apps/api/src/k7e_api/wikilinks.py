"""Parse explicit ``[[wikilink]]`` references out of compiled Markdown.

These are *author/LLM-asserted* links — distinct from the vector-similarity
edges the link-build derives. Supported forms::

    [[Card Apply Workflow]]          -> target "Card Apply Workflow"
    [[card-apply-workflow]]          -> target "card-apply-workflow"
    [[Card Apply Workflow|see here]] -> target "Card Apply Workflow" (alias dropped)

Resolution of a target string to an actual page (by slug or title) happens in
the link-build activity, not here — this module is pure text parsing so it stays
trivially unit-testable.
"""

from __future__ import annotations

import re

# [[ target ]] or [[ target | alias ]]; target may not contain [ ] |
_WIKILINK_RE = re.compile(r"\[\[\s*([^\[\]|]+?)\s*(?:\|[^\[\]]*)?\]\]")


def extract_wikilink_targets(markdown: str) -> list[str]:
    """Return de-duplicated link targets in first-seen order.

    Args:
        markdown: The page body to scan (``None``/empty is allowed).

    Returns:
        Target strings with surrounding whitespace stripped and any ``|alias``
        removed. Duplicates (case-insensitive) are collapsed, keeping the first
        spelling encountered.
    """
    seen: dict[str, str] = {}
    for match in _WIKILINK_RE.finditer(markdown or ""):
        target = match.group(1).strip()
        if target:
            seen.setdefault(target.casefold(), target)
    return list(seen.values())
