"""Tests for OKF resolve (link plan) + the end-to-end ingest orchestrator."""

from __future__ import annotations

from k7e_api.llm_client import StubLLMClient
from k7e_api.okf import OkfFrontmatter, OkfPage
from k7e_api.okf_bundle import OkfBundle
from k7e_api.okf_extract import ExtractedConcept, ExtractedEntity, OkfExtraction
from k7e_api.okf_ingest import ingest_source
from k7e_api.okf_resolve import resolve


def test_resolve_builds_bidirectional_plan(tmp_path):
    b = OkfBundle(tmp_path)
    b.init()
    # seed an existing concept so a reference resolves to it
    b.write_page(
        OkfPage(
            slug="k7e-pattern",
            frontmatter=OkfFrontmatter(type="concept", title="LLM Wiki Pattern"),
            body="x",
        )
    )
    ex = OkfExtraction(
        title="Hot Cache Pattern",
        slug="hot-cache-pattern",
        summary="s",
        entities=[ExtractedEntity(name="Nate Herk", kind="person")],
        concepts=[ExtractedConcept(name="Hot Cache")],
        references=["k7e-pattern"],
    )
    ops = resolve(ex, b, source_slug="hot-cache-pattern")

    source = ops[0]
    assert source.page_type == "source" and source.action == "create"
    # source links to its entities + concepts + the resolved reference
    assert set(source.links) == {"nate-herk", "hot-cache", "k7e-pattern"}
    entity = next(o for o in ops if o.page_type == "entity")
    assert entity.action == "create"
    assert entity.links == ["hot-cache-pattern"]  # back-link to the source


async def test_ingest_writes_linked_pages_and_commits(tmp_path):
    b = OkfBundle(tmp_path)
    res = await ingest_source(
        b, "a source about hot cache", client=StubLLMClient(), today="2026-06-18"
    )
    assert res["commit"]  # an actual git commit happened
    assert res["source_slug"] == "hot-cache-pattern"

    # stub extraction -> a source + an entity + a concept page
    assert b.exists("source", "hot-cache-pattern")
    assert b.exists("entity", "nate-herk")
    assert b.exists("concept", "hot-cache")

    source = b.read_page("source", "hot-cache-pattern")
    assert source.frontmatter.type == "source"
    assert "[[nate-herk]]" in source.body and "[[hot-cache]]" in source.body

    entity = b.read_page("entity", "nate-herk")
    assert entity.frontmatter.sources == ["[[hot-cache-pattern]]"]
    assert "[[hot-cache-pattern]]" in entity.body  # back-link

    assert "[[hot-cache]]" in (tmp_path / "index.md").read_text()
    log = (tmp_path / "log.md").read_text()
    assert "## [2026-06-18] ingest | hot-cache-pattern" in log


async def test_reingest_updates_not_duplicates(tmp_path):
    b = OkfBundle(tmp_path)
    await ingest_source(b, "src", client=StubLLMClient(), today="2026-06-18")
    await ingest_source(b, "src", client=StubLLMClient(), today="2026-06-19")
    # same content -> existing pages are updated, not duplicated
    assert b.list_pages("source") == ["hot-cache-pattern"]
    assert b.list_pages("entity") == ["nate-herk"]
    assert b.list_pages("concept") == ["hot-cache"]


def test_sanitize_links_strips_dangling_inline_links():
    """Compose-invented links to non-existent pages become plain text."""
    from k7e_api.okf_ingest import _sanitize_links

    valid = {"example-bank", "card-types"}
    body = "See [[example-bank]], [[Card Types|cards]], [[用語集]] and [[取説]]."
    out = _sanitize_links(body, valid)

    assert "[[example-bank]]" in out  # known slug kept
    assert "[[Card Types|cards]]" in out  # slugifies to card-types -> kept
    assert "[[用語集]]" not in out and "用語集" in out  # dangling -> de-linked
    assert "[[取説]]" not in out and "取説" in out


async def test_ingest_records_created_and_updated_dates(tmp_path):
    """created is preserved across re-ingest; updated is bumped each time."""
    b = OkfBundle(tmp_path)
    await ingest_source(b, "src", client=StubLLMClient(), today="2026-06-18")
    await ingest_source(b, "src", client=StubLLMClient(), today="2026-06-20")
    page = b.read_page("source", "hot-cache-pattern")
    assert page.frontmatter.created == "2026-06-18"  # preserved
    assert page.frontmatter.updated == "2026-06-20"  # bumped


async def test_ingest_persists_detected_alias_into_existing_page(tmp_path):
    """An extracted entity aliased to an existing page records the alias name."""
    b = OkfBundle(tmp_path)
    b.init()
    b.write_page(
        OkfPage(
            slug="example-bank",
            frontmatter=OkfFrontmatter(type="entity", title="Example Bank"),
            body="# Example Bank\n\nexisting",
        )
    )

    class _AliasClient:
        async def complete_json(self, *, system, user, schema_name):
            if schema_name == "OkfExtraction":
                return {
                    "title": "Example Securities",
                    "slug": "example-securities",
                    "summary": "Brokerage.",
                    "tags": [],
                    "entities": [{"name": "例示銀行", "kind": "org", "description": "Bank."}],
                    "concepts": [],
                    "citations": [],
                    "references": [],
                }
            if schema_name == "OkfRelate":
                return {"related": [], "aliases": {"例示銀行": "example-bank"}}
            if schema_name == "OkfCompose":
                return {"markdown_body": "## Overview\n\nBody.\n"}
            return {}

    await ingest_source(b, "src", client=_AliasClient(), today="2026-06-18")
    bank = b.read_page("entity", "example-bank")
    assert "例示銀行" in bank.frontmatter.aliases
    assert bank.frontmatter.title == "Example Bank"  # canonical title preserved
