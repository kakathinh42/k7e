"""Tests for the OKF resolve step — the deterministic link plan."""

from __future__ import annotations

from k7e_api.okf import OkfFrontmatter, OkfPage
from k7e_api.okf_bundle import OkfBundle
from k7e_api.okf_extract import ExtractedConcept, ExtractedEntity, OkfExtraction
from k7e_api.okf_resolve import resolve


def _bundle_with_source(tmp_path, slug: str) -> OkfBundle:
    bundle = OkfBundle(tmp_path)
    bundle.init()
    bundle.write_page(
        OkfPage(
            slug=slug,
            frontmatter=OkfFrontmatter(type="source", title=slug),
            body="existing source body",
        )
    )
    return bundle


def test_resolve_does_not_fork_existing_cross_type_slug(tmp_path):
    """A concept whose slug already exists as a source must NOT create a page."""
    bundle = _bundle_with_source(tmp_path, "payment-retry-policy")
    extraction = OkfExtraction(
        title="Refunds",
        slug="refunds",
        summary="About refunds.",
        concepts=[ExtractedConcept(name="Payment Retry Policy", description="x")],
    )

    ops = resolve(extraction, bundle, source_slug="refunds")

    # No duplicate concept page for the colliding slug...
    assert not any(op.page_type == "concept" and op.slug == "payment-retry-policy" for op in ops)
    # ...but the source still links to the existing page.
    source_op = next(op for op in ops if op.page_type == "source")
    assert "payment-retry-policy" in source_op.links


def test_resolve_skips_child_equal_to_source_slug(tmp_path):
    bundle = OkfBundle(tmp_path)
    bundle.init()
    extraction = OkfExtraction(
        title="Refunds",
        slug="refunds",
        summary="About refunds.",
        entities=[ExtractedEntity(name="Refunds")],  # slugs to 'refunds' == source
    )

    ops = resolve(extraction, bundle, source_slug="refunds")

    assert [op.page_type for op in ops] == ["source"]  # no self-duplicate page


def test_resolve_dedups_repeated_child_within_one_run(tmp_path):
    bundle = OkfBundle(tmp_path)
    bundle.init()
    extraction = OkfExtraction(
        title="Doc",
        slug="doc",
        summary="...",
        entities=[ExtractedEntity(name="Hot Cache"), ExtractedEntity(name="Hot Cache")],
    )

    ops = resolve(extraction, bundle, source_slug="doc")

    hot = [op for op in ops if op.page_type == "entity" and op.slug == "hot-cache"]
    assert len(hot) == 1
