"""M4: governed `domain` vocabulary + OKF frontmatter field."""

from __future__ import annotations

from typing import get_args

from k7e_api import okf
from k7e_api.okf import DOMAINS, Domain, OkfFrontmatter, OkfPage, coerce_domain


def test_domain_literal_matches_domains_tuple():
    # The Literal (drives 422 validation) and the tuple (drives coerce_domain)
    # are hand-maintained twins; guard against them silently drifting apart.
    assert set(get_args(Domain)) == set(DOMAINS)


def test_coerce_domain_keeps_valid_value():
    assert coerce_domain("backend") == "backend"


def test_coerce_domain_normalizes_case_and_whitespace():
    assert coerce_domain("  Backend ") == "backend"


def test_coerce_domain_rejects_out_of_enum():
    assert coerce_domain("banana") is None


def test_coerce_domain_passes_through_none():
    assert coerce_domain(None) is None


def test_all_domains_coerce_to_themselves():
    assert all(coerce_domain(d) == d for d in DOMAINS)


def test_frontmatter_round_trips_domain():
    page = OkfPage(
        slug="retry-policy",
        frontmatter=OkfFrontmatter(type="concept", title="Retry Policy", domain="backend"),
        body="# Retry Policy\n\nbody",
    )
    text = okf.serialize(page)
    assert "domain: backend" in text
    back = okf.parse(text, slug="retry-policy")
    assert back.frontmatter.domain == "backend"


def test_frontmatter_omits_domain_when_none():
    page = OkfPage(
        slug="x",
        frontmatter=OkfFrontmatter(type="source", title="X"),
        body="# X\n\nbody",
    )
    assert "domain:" not in okf.serialize(page)
