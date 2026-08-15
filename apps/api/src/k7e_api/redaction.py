"""Sensitive-data redaction utilities.

Provides deterministic regex-based redaction for common PII categories:
email addresses and credit-card-like numeric sequences.
"""

from __future__ import annotations

import re

# Matches standard email addresses.
_EMAIL_PATTERN: re.Pattern[str] = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

# Matches credit-card-like sequences: 13–16 digit groups optionally separated
# by spaces or dashes (e.g. Visa 16-digit, Amex 15-digit, Discover 13-digit).
_CC_PATTERN: re.Pattern[str] = re.compile(r"\b(?:\d[ -]*?){13,16}\b")

_EMAIL_REPLACEMENT = "[REDACTED_EMAIL]"
_CC_REPLACEMENT = "[REDACTED_CC]"


def redact(text: str) -> tuple[str, list[str]]:
    """Replace sensitive data in *text* with placeholder tokens.

    Patterns applied (in order):
    1. Email addresses matching ``[\\w.+-]+@[\\w-]+\\.[\\w.-]+`` are replaced
       with ``[REDACTED_EMAIL]``.
    2. Credit-card-like numbers (13–16 consecutive digits, optionally
       separated by spaces or dashes) matching
       ``\\b(?:\\d[ -]*?){13,16}\\b`` are replaced with ``[REDACTED_CC]``.

    Args:
        text: Input text that may contain sensitive data.

    Returns:
        A two-element tuple ``(redacted_text, categories)`` where:

        - *redacted_text* is the input with sensitive tokens replaced.
        - *categories* is a list of category strings indicating which types
          of data were found and replaced.  Each category appears **at most
          once**.  Possible values: ``"email"``, ``"cc"``.  The list is
          empty when nothing was redacted.
    """
    categories: list[str] = []

    # --- Email redaction ---
    redacted, n_subs = _EMAIL_PATTERN.subn(_EMAIL_REPLACEMENT, text)
    if n_subs:
        categories.append("email")
    text = redacted

    # --- Credit-card redaction ---
    redacted, n_subs = _CC_PATTERN.subn(_CC_REPLACEMENT, text)
    if n_subs:
        categories.append("cc")
    text = redacted

    return text, categories
