"""Tests for graph-aware linking + dedup: relate a new source to existing pages."""

from __future__ import annotations

from k7e_api.okf import OkfFrontmatter, OkfPage
from k7e_api.okf_bundle import OkfBundle
from k7e_api.okf_extract import ExtractedEntity, OkfExtraction
from k7e_api.okf_relate import relate_existing
from k7e_api.okf_resolve import resolve


class _RelateStub:
    """Fake LLM returning fixed `related` + `aliases`."""

    def __init__(self, related=None, aliases=None):
        self._related = related or []
        self._aliases = aliases or {}

    async def complete_json(self, *, system, user, schema_name):
        assert schema_name == "OkfRelate"
        return {"related": self._related, "aliases": self._aliases}


def _extraction(entity_name="Example Securities"):
    return OkfExtraction(
        title="Example Securities",
        slug="example-securities",
        summary="An online brokerage in the Example group.",
        entities=[ExtractedEntity(name=entity_name)],
    )


async def test_relate_returns_empty_for_empty_catalog():
    res = await relate_existing(_RelateStub(["example-bank"]), _extraction(), {})
    assert res.related == [] and res.aliases == {}


async def test_relate_keeps_only_catalog_slugs():
    catalog = {"example-bank": "Example Bank", "card-types": "Card Types"}
    stub = _RelateStub(related=["example-bank", "hallucinated", "example-bank"])
    res = await relate_existing(stub, _extraction(), catalog)
    assert res.related == ["example-bank"]  # hallucinated dropped, deduped


async def test_relate_validates_aliases_against_catalog():
    catalog = {"example-bank": "Example Bank"}
    stub = _RelateStub(aliases={"Example Bank": "example-bank", "x": "not-in-catalog"})
    res = await relate_existing(stub, _extraction("Example Bank"), catalog)
    assert res.aliases == {"Example Bank": "example-bank"}  # invalid target dropped


def test_resolve_adds_related_links_to_the_source(tmp_path):
    bundle = OkfBundle(tmp_path)
    bundle.init()
    bundle.write_page(
        OkfPage(
            slug="example-bank",
            frontmatter=OkfFrontmatter(type="entity", title="Example Bank"),
            body="body",
        )
    )
    ops = resolve(
        _extraction(),
        bundle,
        source_slug="example-securities",
        related_slugs=["example-bank", "does-not-exist"],
    )
    source_op = next(o for o in ops if o.page_type == "source")
    assert "example-bank" in source_op.links
    assert "does-not-exist" not in source_op.links


def test_resolve_dedups_aliased_entity_into_existing_page(tmp_path):
    """An entity named 'Example Bank' aliased to existing 'example-bank' must not fork."""
    bundle = OkfBundle(tmp_path)
    bundle.init()
    bundle.write_page(
        OkfPage(
            slug="example-bank",
            frontmatter=OkfFrontmatter(type="entity", title="Example Bank"),
            body="existing",
        )
    )

    ops = resolve(
        _extraction("Example Bank"),
        bundle,
        source_slug="example-securities",
        aliases={"Example Bank": "example-bank"},
    )

    # No new Example Bank page; the existing example-bank is updated (and linked).
    assert not any(o.slug == "Example Bank" for o in ops)
    bank = next((o for o in ops if o.slug == "example-bank"), None)
    assert bank is not None and bank.action == "update"
    source_op = next(o for o in ops if o.page_type == "source")
    assert "example-bank" in source_op.links


async def test_relate_logs_truncation_when_catalog_too_large():
    """A catalog larger than MAX_CATALOG emits an okf_catalog_truncated warning."""
    from k7e_api.okf_relate import MAX_CATALOG
    from structlog.testing import capture_logs

    catalog = {f"slug-{i}": f"Title {i}" for i in range(MAX_CATALOG + 5)}
    with capture_logs() as logs:
        await relate_existing(_RelateStub(), _extraction(), catalog)

    events = [e for e in logs if e.get("event") == "okf_catalog_truncated"]
    assert events, "expected a truncation warning"
    assert events[0]["total"] == MAX_CATALOG + 5
    assert events[0]["used"] == MAX_CATALOG


async def test_relate_does_not_log_when_catalog_small():
    """No warning when the catalog fits under MAX_CATALOG."""
    from structlog.testing import capture_logs

    with capture_logs() as logs:
        await relate_existing(_RelateStub(), _extraction(), {"example-bank": "Example Bank"})

    assert not [e for e in logs if e.get("event") == "okf_catalog_truncated"]


def test_resolve_records_alias_name_on_reused_page(tmp_path):
    """When an entity is aliased to an existing page, the alias name is recorded."""
    bundle = OkfBundle(tmp_path)
    bundle.init()
    bundle.write_page(
        OkfPage(
            slug="example-bank",
            frontmatter=OkfFrontmatter(type="entity", title="Example Bank"),
            body="existing",
        )
    )
    ops = resolve(
        _extraction("例示銀行"),
        bundle,
        source_slug="example-securities",
        aliases={"例示銀行": "example-bank"},
    )
    bank = next(o for o in ops if o.slug == "example-bank")
    assert bank.aliases == ["例示銀行"]
