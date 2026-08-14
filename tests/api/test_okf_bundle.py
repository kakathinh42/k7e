"""Tests for the git-backed OKF bundle store."""

from __future__ import annotations

from k7e_api.okf import OkfFrontmatter, OkfPage
from k7e_api.okf_bundle import OkfBundle


def _page(slug, ptype, title):
    return OkfPage(
        slug=slug,
        frontmatter=OkfFrontmatter(type=ptype, title=title),
        body=f"# {title}\n\nbody linking [[other]]",
    )


def test_init_creates_layout_and_git(tmp_path):
    b = OkfBundle(tmp_path)
    b.init()
    for sub in ("sources", "entities", "concepts", "analyses"):
        assert (tmp_path / sub).is_dir()
    assert (tmp_path / ".git").exists()
    assert (tmp_path / "index.md").exists()
    assert (tmp_path / "log.md").exists()


def test_write_read_list_slugs(tmp_path):
    b = OkfBundle(tmp_path)
    b.init()
    b.write_page(_page("hot-cache", "concept", "Hot Cache"))
    assert b.exists("concept", "hot-cache")
    page = b.read_page("concept", "hot-cache")
    assert page.frontmatter.title == "Hot Cache"
    assert b.list_pages("concept") == ["hot-cache"]
    assert b.all_slugs()["concept"] == {"hot-cache"}
    assert b.read_page("concept", "missing") is None


def test_index_and_log(tmp_path):
    b = OkfBundle(tmp_path)
    b.init()
    b.write_page(_page("a", "concept", "A"))
    b.update_index()
    idx = (tmp_path / "index.md").read_text()
    assert "[[a]]" in idx and "Concepts" in idx
    b.append_log("did a thing", timestamp="2026-06-18")
    assert "2026-06-18 did a thing" in (tmp_path / "log.md").read_text()


def test_commit_and_noop(tmp_path):
    b = OkfBundle(tmp_path)
    b.init()
    b.write_page(_page("a", "concept", "A"))
    short_hash = b.commit("first")
    assert short_hash  # something was committed
    assert b.commit("nothing changed") is None


def test_init_writes_gitignore_for_lock_file(tmp_path):
    b = OkfBundle(tmp_path)
    b.init()
    assert (tmp_path / ".gitignore").read_text().strip() == ".okf.lock"


def test_lock_blocks_a_second_writer(tmp_path):
    import pytest
    from filelock import Timeout

    b = OkfBundle(tmp_path)
    b.init()
    with b.lock():
        with pytest.raises(Timeout):
            b.lock(timeout=0.1).acquire()


def test_index_renders_tables_with_summary_and_date(tmp_path):
    b = OkfBundle(tmp_path)
    b.init()
    b.write_page(
        OkfPage(
            slug="src1",
            frontmatter=OkfFrontmatter(
                type="source",
                title="Src 1",
                description="A source summary.",
                updated="2026-06-18",
            ),
            body="# Src 1\n\nbody",
        )
    )
    b.write_page(
        OkfPage(
            slug="a",
            frontmatter=OkfFrontmatter(
                type="concept", title="A", description="Concept A summary."
            ),
            body="# A\n\nbody",
        )
    )
    b.update_index()
    idx = (tmp_path / "index.md").read_text()
    assert "## Sources" in idx and "## Concepts" in idx
    assert "| Page | Summary | Date |" in idx  # sources table has a date column
    assert "[[src1]]" in idx and "A source summary." in idx and "2026-06-18" in idx
    assert "[[a]]" in idx and "Concept A summary." in idx


def test_append_log_entry_writes_structured_block(tmp_path):
    b = OkfBundle(tmp_path)
    b.init()
    b.append_log_entry(
        op="ingest",
        subject="hot-cache-pattern",
        created=["hot-cache-pattern", "nate-herk"],
        updated=["hot-cache"],
        timestamp="2026-06-18",
    )
    log = (tmp_path / "log.md").read_text()
    assert "## [2026-06-18] ingest | hot-cache-pattern" in log
    assert "- **Pages created:**" in log and "[[nate-herk]]" in log
    assert "- **Pages updated:**" in log and "[[hot-cache]]" in log
