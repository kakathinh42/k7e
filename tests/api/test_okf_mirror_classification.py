"""M4: mirror promotes domain + syncs item_tags (incremental, backfill)."""

from __future__ import annotations

from k7e_api.models import ItemTag, KnowledgeItem
from k7e_api.okf import OkfFrontmatter, OkfPage
from k7e_api.okf_bundle import OkfBundle
from k7e_api.okf_mirror import _normalize_tags, mirror_bundle


def test_normalize_tags_trims_lowercases_dedupes_drops_empty():
    assert _normalize_tags(["  Redis ", "redis", "", "  ", "Cache"]) == [
        "redis",
        "cache",
    ]


def _write(bundle, slug, *, domain=None, tags=None, body="# T\n\nbody"):
    bundle.write_page(
        OkfPage(
            slug=slug,
            frontmatter=OkfFrontmatter(type="source", title=slug, domain=domain, tags=tags or []),
            body=body,
        )
    )


async def test_mirror_promotes_domain_and_tags(tmp_path, sqlite_factory):
    bundle = OkfBundle(tmp_path)
    bundle.init()
    _write(bundle, "p", domain="backend", tags=["redis", "cache"])

    with sqlite_factory() as s:
        await mirror_bundle(s, bundle)

    with sqlite_factory() as s:
        item = s.query(KnowledgeItem).filter_by(slug="p").one()
        assert item.domain == "backend"
        assert {t.tag for t in s.query(ItemTag).filter_by(item_id=item.id)} == {
            "redis",
            "cache",
        }


async def test_mirror_invalid_domain_becomes_null(tmp_path, sqlite_factory):
    bundle = OkfBundle(tmp_path)
    bundle.init()
    _write(bundle, "p", domain="bogus", tags=[])
    with sqlite_factory() as s:
        await mirror_bundle(s, bundle)
    with sqlite_factory() as s:
        assert s.query(KnowledgeItem).filter_by(slug="p").one().domain is None


async def test_mirror_tag_sync_adds_and_removes(tmp_path, sqlite_factory):
    bundle = OkfBundle(tmp_path)
    bundle.init()
    _write(bundle, "p", tags=["a", "b"], body="# v1\n\nbody one")
    with sqlite_factory() as s:
        await mirror_bundle(s, bundle)

    # Change tags AND body (body change forces a new version / non-skip).
    _write(bundle, "p", tags=["b", "c"], body="# v2\n\nbody two changed")
    with sqlite_factory() as s:
        await mirror_bundle(s, bundle)

    with sqlite_factory() as s:
        item = s.query(KnowledgeItem).filter_by(slug="p").one()
        assert {t.tag for t in s.query(ItemTag).filter_by(item_id=item.id)} == {
            "b",
            "c",
        }


async def test_mirror_is_idempotent_on_tags(tmp_path, sqlite_factory):
    bundle = OkfBundle(tmp_path)
    bundle.init()
    _write(bundle, "p", tags=["a", "b"])
    with sqlite_factory() as s:
        await mirror_bundle(s, bundle)
    with sqlite_factory() as s:
        await mirror_bundle(s, bundle)  # re-mirror
    with sqlite_factory() as s:
        item = s.query(KnowledgeItem).filter_by(slug="p").one()
        assert s.query(ItemTag).filter_by(item_id=item.id).count() == 2  # no dupes
