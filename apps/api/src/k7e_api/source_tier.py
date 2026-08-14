"""Resolve a source's tier ('A' authoritative/page-like | 'B' conversational).

Tier is provenance metadata, not inferred from file content (the same Markdown
could be a Confluence export or pasted meeting notes). The caller — a connector
or the upload endpoint — may declare it explicitly; otherwise we fall back to a
per-source-system default.
"""

from __future__ import annotations

VALID_TIERS = ("A", "B")

# Default tier per known source system. Conversational systems default to 'B'.
SOURCE_TIER_DEFAULTS: dict[str, str] = {
    "zoom": "B",
    "slack": "B",
    "chat_agent": "B",
    "meeting_notes": "B",
    "confluence": "A",
    "wikipedia": "A",
    "internal-wiki": "A",
    "jira": "A",
    "manual_upload": "A",
    "filesystem": "A",
}


def resolve_source_tier(source_system: str, explicit: str | None = None) -> str:
    """Return 'A' or 'B'.

    An explicit value wins (case-insensitive, validated); otherwise fall back to
    the per-source-system default, and 'A' for unknown systems.

    Raises:
        ValueError: if ``explicit`` is given but is not 'A' or 'B'.
    """
    if explicit:
        tier = explicit.upper()
        if tier not in VALID_TIERS:
            raise ValueError(f"invalid source_tier: {explicit!r} (expected A or B)")
        return tier
    return SOURCE_TIER_DEFAULTS.get(source_system, "A")
