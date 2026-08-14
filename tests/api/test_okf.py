"""Tests for the OKF page model + extract pass."""

from __future__ import annotations

from k7e_api import okf
from k7e_api.llm_client import StubLLMClient
from k7e_api.okf import OkfFrontmatter, OkfPage
from k7e_api.okf_extract import OkfExtraction, build_extract_prompt, extract_okf
from k7e_api.wikilinks import extract_wikilink_targets


def test_serialize_parse_round_trip():
    page = OkfPage(
        slug="hot-cache",
        frontmatter=OkfFrontmatter(
            type="concept",
            title="Hot Cache",
            description="A rolling recent-context file.",
            tags=["concept", "agent-memory"],
            timestamp="2026-06-18",
            sources=["[[nate-herk-video]]"],
        ),
        body="# Hot Cache\n\nSee [[k7e-pattern]] and [[context-restore|restore]].",
    )
    text = okf.serialize(page)
    assert text.startswith("---\n")
    assert "type: concept" in text

    back = okf.parse(text, slug="hot-cache")
    assert back.frontmatter.type == "concept"
    assert back.frontmatter.title == "Hot Cache"
    assert back.frontmatter.tags == ["concept", "agent-memory"]
    assert back.frontmatter.sources == ["[[nate-herk-video]]"]
    assert "[[k7e-pattern]]" in back.body
    # links are extractable for the graph mirror
    assert set(extract_wikilink_targets(back.body)) == {
        "k7e-pattern",
        "context-restore",
    }


def test_type_is_the_only_hard_requirement_extras_allowed():
    page = okf.parse("---\ntype: source\ntitle: T\ncustom_field: hello\n---\n\nbody")
    assert page.frontmatter.type == "source"
    assert page.frontmatter.custom_field == "hello"  # OKF allows extra fields


def test_parse_requires_frontmatter():
    import pytest

    with pytest.raises(ValueError):
        okf.parse("no frontmatter here")


def test_page_path_and_helpers():
    assert okf.page_path("concept", "hot-cache") == "concepts/hot-cache.md"
    assert okf.page_path("source", "x") == "sources/x.md"
    assert okf.wikilink("a") == "[[a]]"
    assert okf.wikilink("a", "Alias") == "[[a|Alias]]"
    assert okf.slugify("Hello, World!") == "hello-world"


def test_slugify_is_unicode_aware():
    # Non-Latin (e.g. Japanese) names get a real, distinct slug — not "untitled".
    assert okf.slugify("旧例示クレジット") == "旧例示クレジット"
    assert okf.slugify("審査・保証") == "審査-保証"
    assert okf.slugify("旧例示クレジット") != okf.slugify("審査・保証")
    # Only a truly empty name falls back to "untitled"; pure punctuation hashes.
    assert okf.slugify("   ") == "untitled"
    assert okf.slugify("!!!").startswith("page-")
    assert okf.slugify("???") != okf.slugify("!!!")  # distinct punctuation -> distinct


def test_build_extract_prompt_lists_the_schema_keys():
    p = build_extract_prompt("some source")
    for key in ("entities", "concepts", "citations", "references", "summary"):
        assert key in p


async def test_extract_okf_returns_typed_knowledge():
    result = await extract_okf(StubLLMClient(), "a source about hot cache")
    assert isinstance(result, OkfExtraction)
    assert result.entities[0].name == "Nate Herk"
    assert result.concepts[0].name == "Hot Cache"
    assert result.citations and result.references


def test_frontmatter_carries_aliases_created_updated():
    page = OkfPage(
        slug="example-bank",
        frontmatter=OkfFrontmatter(
            type="entity",
            title="Example Bank",
            aliases=["Example Bank"],
            created="2026-06-01",
            updated="2026-06-18",
        ),
        body="body",
    )
    back = okf.parse(okf.serialize(page), slug="example-bank")
    assert back.frontmatter.aliases == ["Example Bank"]
    assert back.frontmatter.created == "2026-06-01"
    assert back.frontmatter.updated == "2026-06-18"


def test_frontmatter_omits_unset_optional_dates():
    """created/updated default to None and are excluded from serialized YAML."""
    page = OkfPage(slug="x", frontmatter=OkfFrontmatter(type="source", title="X"), body="b")
    text = okf.serialize(page)
    assert "created:" not in text
    assert "updated:" not in text
