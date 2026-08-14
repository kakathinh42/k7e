"""Tests for mirroring an OKF bundle into Postgres (items + chunks + links)."""

from __future__ import annotations

from k7e_api.models import KnowledgeItem, Organization, Space, WikiChunk, WikiLink
from k7e_api.okf import OkfFrontmatter, OkfPage
from k7e_api.okf_bundle import OkfBundle
from k7e_api.okf_mirror import mirror_bundle


def _write(bundle, slug, ptype, title, body):
    bundle.write_page(
        OkfPage(slug=slug, frontmatter=OkfFrontmatter(type=ptype, title=title), body=body)
    )


async def test_mirror_creates_items_chunks_and_explicit_links(tmp_path, sqlite_factory):
    bundle = OkfBundle(tmp_path)
    bundle.init()
    _write(
        bundle,
        "hot-cache-pattern",
        "source",
        "Hot Cache Pattern",
        "# Hot Cache Pattern\n\nSee [[hot-cache]] and [[nate-herk]].",
    )
    _write(
        bundle,
        "hot-cache",
        "concept",
        "Hot Cache",
        "# Hot Cache\n\nA rolling context file.",
    )
    _write(bundle, "nate-herk", "entity", "Nate Herk", "# Nate Herk\n\nIntroduced it.")

    with sqlite_factory() as s:
        res = await mirror_bundle(s, bundle)
        assert res["pages"] == 3
        assert res["links"] == 2  # source -> hot-cache, source -> nate-herk

    with sqlite_factory() as s:
        items = {i.slug: i for i in s.query(KnowledgeItem).all()}
        assert set(items) == {"hot-cache-pattern", "hot-cache", "nate-herk"}
        assert all(i.status == "published" and i.current_version_id for i in items.values())
        assert s.query(WikiChunk).count() >= 3  # chunk text written

        links = s.query(WikiLink).filter(WikiLink.origin == "explicit").all()
        src = items["hot-cache-pattern"].id
        targets = {link.target_item_id for link in links if link.source_item_id == src}
        assert targets == {items["hot-cache"].id, items["nate-herk"].id}


async def test_mirror_is_idempotent(tmp_path, sqlite_factory):
    bundle = OkfBundle(tmp_path)
    bundle.init()
    _write(bundle, "a", "concept", "A", "# A\n\nlinks [[b]]")
    _write(bundle, "b", "concept", "B", "# B\n\nplain")

    for _ in range(2):  # mirror twice
        with sqlite_factory() as s:
            await mirror_bundle(s, bundle)

    with sqlite_factory() as s:
        assert s.query(KnowledgeItem).count() == 2  # not duplicated
        assert (
            s.query(WikiLink).filter(WikiLink.origin == "explicit").count() == 1
        )  # links rebuilt, not doubled


async def test_mirror_is_incremental(tmp_path, sqlite_factory):
    """Unchanged pages are skipped on re-mirror: no new version, no re-chunk."""
    bundle = OkfBundle(tmp_path)
    bundle.init()
    _write(bundle, "a", "concept", "A", "# A\n\nbody")

    with sqlite_factory() as s:
        first = await mirror_bundle(s, bundle)
        assert first["changed"] == 1

    # Re-mirror the same bundle -> nothing changed.
    with sqlite_factory() as s:
        second = await mirror_bundle(s, bundle)
        assert second["changed"] == 0

    # Add a new page -> only it is re-chunked; "a" stays at one version.
    _write(bundle, "b", "concept", "B", "# B\n\nbody")
    with sqlite_factory() as s:
        third = await mirror_bundle(s, bundle)
        assert third["changed"] == 1

    with sqlite_factory() as s:
        from k7e_api.models import KnowledgeItemVersion

        a = s.query(KnowledgeItem).filter_by(slug="a").one()
        a_versions = s.query(KnowledgeItemVersion).filter_by(item_id=a.id).count()
        assert a_versions == 1  # never re-versioned across three mirrors


async def test_mirror_writes_chunk_text_without_embedding(tmp_path, sqlite_factory):
    """The mirror writes chunk TEXT with embedding=NULL; it never calls the gateway.

    Replaces the old embed-failure / embed-disabled tests: embedding was moved out
    of the mirror into the scheduled backfill, so the mirror is gateway-independent.
    """
    bundle = OkfBundle(tmp_path)
    bundle.init()
    _write(bundle, "a", "concept", "A", "# A\n\nbody")

    with sqlite_factory() as s:
        res = await mirror_bundle(s, bundle)
        assert res["pages"] == 1

    with sqlite_factory() as s:
        item = s.query(KnowledgeItem).filter_by(slug="a").one()
        assert item.status == "published"  # searchable by keyword
        chunks = s.query(WikiChunk).all()
        assert chunks  # chunk text is written immediately
        assert all(c.chunk_text for c in chunks)
        assert all(c.embedding is None for c in chunks)  # vectors filled by backfill


async def test_mirror_tolerates_cross_type_slug_collision(tmp_path, sqlite_factory):
    """Two pages sharing a slug across type dirs must not crash the link rebuild.

    Regression for a uq_wiki_link UniqueViolation: a source AND a concept named
    'dup' both linking to the same target collapsed into one KnowledgeItem and
    double-inserted the (src, tgt) edge.
    """
    bundle = OkfBundle(tmp_path)
    bundle.init()
    # Same slug 'dup' in two type dirs, both linking to [[target]].
    _write(bundle, "dup", "source", "Dup", "# Dup source\n\nlinks [[target]]")
    _write(bundle, "dup", "concept", "Dup", "# Dup concept\n\nlinks [[target]]")
    _write(bundle, "target", "concept", "Target", "# Target\n\nplain")

    with sqlite_factory() as s:
        res = await mirror_bundle(s, bundle)

    with sqlite_factory() as s:
        # One item per slug (collision collapsed), and exactly one dup->target edge.
        assert s.query(KnowledgeItem).filter_by(slug="dup").count() == 1
        dup = s.query(KnowledgeItem).filter_by(slug="dup").one()
        edges = (
            s.query(WikiLink)
            .filter(WikiLink.source_item_id == dup.id, WikiLink.origin == "explicit")
            .count()
        )
        assert edges == 1
        assert res["pages"] == 2  # collided page dropped from the mirror set


async def test_mirror_creates_link_to_pre_existing_page(tmp_path, sqlite_factory):
    """A page linking to a pre-existing DB item (not in this run) gets the explicit edge.

    Regression guard for the batch-resolve fix in mirror_bundle Pass 2: ensures
    that cross-run wikilink targets are resolved correctly whether via the old
    per-slug fallback or the new bulk pre-resolution.
    """
    # Seed a pre-existing item directly into the DB — NOT via mirror_bundle.
    with sqlite_factory() as s:
        from k7e_api.models import KnowledgeItemVersion as _KIV

        pre = KnowledgeItem(slug="pre-existing", title="Pre Existing", status="published")
        s.add(pre)
        s.flush()
        ver = _KIV(
            item_id=pre.id,
            version_number=1,
            markdown_body="# Pre Existing\n\nsome content",
            model_id="test",
            created_by="test",
            citations=[],
            status="published",
            title="Pre Existing",
        )
        s.add(ver)
        s.flush()
        pre.current_version_id = ver.id
        s.commit()

    # Bundle contains only the new page; pre-existing is NOT part of this run.
    bundle = OkfBundle(tmp_path)
    bundle.init()
    _write(
        bundle,
        "new-page",
        "source",
        "New Page",
        "# New Page\n\nSee [[pre-existing]] for background.",
    )

    with sqlite_factory() as s:
        res = await mirror_bundle(s, bundle)
        assert res["links"] == 1, f"Expected 1 cross-run link, got {res}"

    with sqlite_factory() as s:
        items = {i.slug: i for i in s.query(KnowledgeItem).all()}
        assert "new-page" in items
        assert "pre-existing" in items
        link = (
            s.query(WikiLink)
            .filter(
                WikiLink.source_item_id == items["new-page"].id,
                WikiLink.target_item_id == items["pre-existing"].id,
                WikiLink.origin == "explicit",
            )
            .one_or_none()
        )
        assert link is not None, "Expected explicit link from new-page to pre-existing"


async def test_mirror_persists_page_type(tmp_path, sqlite_factory):
    """Each mirrored KnowledgeItem.type matches its OKF bundle directory."""
    bundle = OkfBundle(tmp_path)
    bundle.init()
    _write(bundle, "the-source", "source", "The Source", "# The Source\n\nbody")
    _write(bundle, "the-entity", "entity", "The Entity", "# The Entity\n\nbody")
    _write(bundle, "the-concept", "concept", "The Concept", "# The Concept\n\nbody")

    with sqlite_factory() as s:
        await mirror_bundle(s, bundle)

    with sqlite_factory() as s:
        items = {i.slug: i for i in s.query(KnowledgeItem).all()}
        assert items["the-source"].type == "source"
        assert items["the-entity"].type == "entity"
        assert items["the-concept"].type == "concept"


async def test_mirror_collision_keeps_source_type(tmp_path, sqlite_factory):
    """When a slug exists as both source and concept, the surviving row is 'source'."""
    bundle = OkfBundle(tmp_path)
    bundle.init()
    # First-seen precedence is source > entity > concept > analysis.
    _write(bundle, "dup", "source", "Dup", "# Dup source\n\nbody")
    _write(bundle, "dup", "concept", "Dup", "# Dup concept\n\nbody")

    with sqlite_factory() as s:
        await mirror_bundle(s, bundle)

    with sqlite_factory() as s:
        dup = s.query(KnowledgeItem).filter_by(slug="dup").one()
        assert dup.type == "source"


async def test_mirror_corrects_type_on_unchanged_remirror(tmp_path, sqlite_factory):
    """A pre-existing row whose content is UNCHANGED still gets its type corrected.

    Simulates a backfilled legacy row (type defaulted to 'source') whose true
    type is 'concept'. The page body/title match the bundle exactly, so Pass 1
    hits the incremental-skip path — yet type must still be corrected because it
    is assigned before the skip check. This locks the backfill fix.
    """
    from k7e_api.models import KnowledgeItemVersion

    body = "# Payment Retry\n\nbody"
    title = "Payment Retry"

    # Seed a published item with the WRONG (default) type but matching content.
    with sqlite_factory() as s:
        item = KnowledgeItem(slug="payment-retry", title=title, status="published", type="source")
        s.add(item)
        s.flush()
        ver = KnowledgeItemVersion(
            item_id=item.id,
            version_number=1,
            markdown_body=body,
            model_id="seed",
            created_by="seed",
            citations=[],
            status="published",
            title=title,
        )
        s.add(ver)
        s.flush()
        item.current_version_id = ver.id
        s.commit()

    # The bundle declares the same slug as a concept, with identical content.
    bundle = OkfBundle(tmp_path)
    bundle.init()
    _write(bundle, "payment-retry", "concept", title, body)

    with sqlite_factory() as s:
        res = await mirror_bundle(s, bundle)
        assert res["changed"] == 0, "content unchanged → no new version (skip path)"

    with sqlite_factory() as s:
        corrected = s.query(KnowledgeItem).filter_by(slug="payment-retry").one()
        assert corrected.type == "concept", "type must be corrected on the skip path"

        from k7e_api.models import KnowledgeItemVersion

        assert s.query(KnowledgeItemVersion).count() == 1, (
            "skip path must not create a new version"
        )


async def test_mirror_persists_provenance(tmp_path, sqlite_factory):
    """Source page stores its resource; derived page stores source_pages slugs."""
    bundle = OkfBundle(tmp_path)
    bundle.init()
    bundle.write_page(
        OkfPage(
            slug="api-rate-limiting",
            frontmatter=OkfFrontmatter(
                type="source", title="API Rate Limiting", resource="abc123sha"
            ),
            body="# API Rate Limiting\n\nbody",
        )
    )
    bundle.write_page(
        OkfPage(
            slug="token-bucket",
            frontmatter=OkfFrontmatter(
                type="concept",
                title="Token Bucket",
                sources=["[[api-rate-limiting]]"],
            ),
            body="# Token Bucket\n\nbody",
        )
    )

    with sqlite_factory() as s:
        await mirror_bundle(s, bundle)

    with sqlite_factory() as s:
        items = {i.slug: i for i in s.query(KnowledgeItem).all()}
        assert items["api-rate-limiting"].provenance == {
            "resource": "abc123sha",
            "source_pages": [],
        }
        assert items["token-bucket"].provenance == {
            "resource": None,
            "source_pages": ["api-rate-limiting"],
        }


async def test_mirror_backfills_provenance_on_unchanged_remirror(tmp_path, sqlite_factory):
    """A pre-existing item with provenance=None gets it populated on an unchanged re-mirror."""
    from k7e_api.models import KnowledgeItemVersion

    body = "# API Rate Limiting\n\nbody"
    title = "API Rate Limiting"

    with sqlite_factory() as s:
        item = KnowledgeItem(
            slug="api-rate-limiting",
            title=title,
            status="published",
            type="source",
            provenance=None,
        )
        s.add(item)
        s.flush()
        ver = KnowledgeItemVersion(
            item_id=item.id,
            version_number=1,
            markdown_body=body,
            model_id="seed",
            created_by="seed",
            citations=[],
            status="published",
            title=title,
        )
        s.add(ver)
        s.flush()
        item.current_version_id = ver.id
        s.commit()

    bundle = OkfBundle(tmp_path)
    bundle.init()
    bundle.write_page(
        OkfPage(
            slug="api-rate-limiting",
            frontmatter=OkfFrontmatter(type="source", title=title, resource="sha-xyz"),
            body=body,
        )
    )

    with sqlite_factory() as s:
        res = await mirror_bundle(s, bundle)
        assert res["changed"] == 0, "content unchanged → skip path"

    with sqlite_factory() as s:
        item = s.query(KnowledgeItem).filter_by(slug="api-rate-limiting").one()
        assert item.provenance == {"resource": "sha-xyz", "source_pages": []}


async def test_mirror_provenance_dedupes_source_pages(tmp_path, sqlite_factory):
    """Duplicate source wikilinks collapse to a single slug, order preserved."""
    bundle = OkfBundle(tmp_path)
    bundle.init()
    bundle.write_page(
        OkfPage(
            slug="derived",
            frontmatter=OkfFrontmatter(
                type="concept",
                title="Derived",
                sources=["[[page-one]]", "[[Page-One]]", "[[page-two]]"],
            ),
            body="# Derived\n\nbody",
        )
    )
    with sqlite_factory() as s:
        await mirror_bundle(s, bundle)
    with sqlite_factory() as s:
        item = s.query(KnowledgeItem).filter_by(slug="derived").one()
        assert item.provenance["source_pages"] == ["page-one", "page-two"]


async def test_mirror_rechunks_page_missing_chunks(tmp_path, sqlite_factory):
    """A content-unchanged page with no chunks is re-chunked on the next mirror.

    Guards the ``item.id not in items_with_chunks`` branch of the skip path: a
    legacy row synced before it had chunks (or one whose chunks were cleared)
    must get its chunk text (re)written on the next mirror without a new version.
    """
    bundle = OkfBundle(tmp_path)
    bundle.init()
    _write(bundle, "a", "concept", "A", "# A\n\nbody")

    # First mirror writes chunks; clear them to simulate a chunk-less synced page.
    with sqlite_factory() as s:
        await mirror_bundle(s, bundle)
    with sqlite_factory() as s:
        s.query(WikiChunk).delete()
        s.commit()
        assert s.query(WikiChunk).count() == 0

    # Second mirror: content unchanged BUT missing chunks -> re-chunk on skip path.
    with sqlite_factory() as s:
        res = await mirror_bundle(s, bundle)
        assert res["changed"] == 0  # content unchanged -> no new version

    with sqlite_factory() as s:
        from k7e_api.models import KnowledgeItemVersion

        assert s.query(WikiChunk).count() > 0  # chunk text re-written
        a = s.query(KnowledgeItem).filter_by(slug="a").one()
        # Re-chunk must not create a new version.
        assert s.query(KnowledgeItemVersion).filter_by(item_id=a.id).count() == 1


async def test_mirror_sets_source_allowed_groups_from_raw_document(tmp_path, sqlite_factory):
    """A source page inherits allowed_groups from its RawDocument (matched by sha256)."""
    from k7e_api.models import RawDocument
    from k7e_api.okf import OkfFrontmatter, OkfPage

    sha = "d" * 64
    with sqlite_factory() as s:
        s.add(
            RawDocument(
                filename="secret.md",
                sha256=sha,
                object_store_ref="raw/x",
                mime_type="text/markdown",
                allowed_groups=["finance"],
            )
        )
        s.commit()

    bundle = OkfBundle(tmp_path)
    bundle.init()
    bundle.write_page(
        OkfPage(
            slug="secret-doc",
            frontmatter=OkfFrontmatter(type="source", title="Secret", resource=sha),
            body="# Secret\n\nbody",
        )
    )

    with sqlite_factory() as s:
        await mirror_bundle(s, bundle)

    with sqlite_factory() as s:
        item = s.query(KnowledgeItem).filter_by(slug="secret-doc").one()
        assert item.allowed_groups == ["finance"]


async def test_mirror_source_without_raw_document_is_public(tmp_path, sqlite_factory):
    """A source page whose resource matches no RawDocument stays public (null)."""
    from k7e_api.okf import OkfFrontmatter, OkfPage

    bundle = OkfBundle(tmp_path)
    bundle.init()
    bundle.write_page(
        OkfPage(
            slug="open-doc",
            frontmatter=OkfFrontmatter(type="source", title="Open", resource="nomatch"),
            body="# Open\n\nbody",
        )
    )
    with sqlite_factory() as s:
        await mirror_bundle(s, bundle)
    with sqlite_factory() as s:
        item = s.query(KnowledgeItem).filter_by(slug="open-doc").one()
        assert item.allowed_groups is None


async def test_mirror_updates_source_allowed_groups_on_remirror(tmp_path, sqlite_factory):
    """A re-mirror of UNCHANGED content propagates a changed RawDocument.allowed_groups."""
    from k7e_api.models import RawDocument
    from k7e_api.okf import OkfFrontmatter, OkfPage

    sha = "e" * 64
    body = "# Doc\n\nbody"
    bundle = OkfBundle(tmp_path)
    bundle.init()
    bundle.write_page(
        OkfPage(
            slug="doc",
            frontmatter=OkfFrontmatter(type="source", title="Doc", resource=sha),
            body=body,
        )
    )

    with sqlite_factory() as s:
        s.add(
            RawDocument(
                filename="d.md",
                sha256=sha,
                object_store_ref="raw/x",
                mime_type="text/markdown",
                allowed_groups=None,
            )
        )
        s.commit()
    with sqlite_factory() as s:
        await mirror_bundle(s, bundle)
    with sqlite_factory() as s:
        assert s.query(KnowledgeItem).filter_by(slug="doc").one().allowed_groups is None

    with sqlite_factory() as s:
        raw = s.query(RawDocument).filter_by(sha256=sha).one()
        raw.allowed_groups = ["finance"]
        s.commit()
    with sqlite_factory() as s:
        res = await mirror_bundle(s, bundle)
        assert res["changed"] == 0  # content unchanged → skip path
    with sqlite_factory() as s:
        assert s.query(KnowledgeItem).filter_by(slug="doc").one().allowed_groups == ["finance"]


async def test_mirror_derived_page_does_not_inherit_allowed_groups(tmp_path, sqlite_factory):
    """A derived (concept) page must NOT get allowed_groups even if its resource matches."""
    from k7e_api.models import RawDocument
    from k7e_api.okf import OkfFrontmatter, OkfPage

    sha = "f" * 64
    with sqlite_factory() as s:
        s.add(
            RawDocument(
                filename="x.md",
                sha256=sha,
                object_store_ref="raw/x",
                mime_type="text/markdown",
                allowed_groups=["finance"],
            )
        )
        s.commit()
    bundle = OkfBundle(tmp_path)
    bundle.init()
    bundle.write_page(
        OkfPage(
            slug="a-concept",
            frontmatter=OkfFrontmatter(type="concept", title="A Concept", resource=sha),
            body="# A Concept\n\nbody",
        )
    )
    with sqlite_factory() as s:
        await mirror_bundle(s, bundle)
    with sqlite_factory() as s:
        assert s.query(KnowledgeItem).filter_by(slug="a-concept").one().allowed_groups is None


# ---------------------------------------------------------------------------
# Per-space mirror tests (Task 4.3 — M1 multi-org)
# ---------------------------------------------------------------------------


async def test_mirror_stamps_space_id_on_items(tmp_path, sqlite_factory):
    """mirror_bundle stamps org_id and space_id on every KnowledgeItem it writes.

    Two spaces under the same org each mirror a distinct page; the resulting
    items carry the correct space_id with no collision (distinct slugs per space).
    """
    with sqlite_factory() as s:
        org = Organization(slug="acme", name="Acme Corp")
        s.add(org)
        s.flush()
        space_eng = Space(org_id=org.id, slug="engineering", name="Engineering")
        space_mkt = Space(org_id=org.id, slug="marketing", name="Marketing")
        s.add_all([space_eng, space_mkt])
        s.commit()

    # Engineering bundle: one page
    bundle_eng = OkfBundle(tmp_path / "eng")
    bundle_eng.init()
    _write(bundle_eng, "eng-guide", "concept", "Eng Guide", "# Eng Guide\n\nbody")

    # Marketing bundle: one page
    bundle_mkt = OkfBundle(tmp_path / "mkt")
    bundle_mkt.init()
    _write(bundle_mkt, "mkt-intro", "concept", "Mkt Intro", "# Mkt Intro\n\nbody")

    with sqlite_factory() as s:
        sp_eng = s.query(Space).filter_by(slug="engineering").one()
        sp_mkt = s.query(Space).filter_by(slug="marketing").one()
        await mirror_bundle(s, bundle_eng, space=sp_eng)
        await mirror_bundle(s, bundle_mkt, space=sp_mkt)

    with sqlite_factory() as s:
        items = {i.slug: i for i in s.query(KnowledgeItem).all()}
        assert "eng-guide" in items, "engineering page must be created"
        assert "mkt-intro" in items, "marketing page must be created"

        sp_eng = s.query(Space).filter_by(slug="engineering").one()
        sp_mkt = s.query(Space).filter_by(slug="marketing").one()
        org = s.query(Organization).filter_by(slug="acme").one()

        eng_item = items["eng-guide"]
        mkt_item = items["mkt-intro"]

        assert eng_item.space_id == sp_eng.id, (
            f"eng-guide must carry engineering space_id, got {eng_item.space_id}"
        )
        assert eng_item.org_id == org.id, f"eng-guide must carry org_id, got {eng_item.org_id}"
        assert mkt_item.space_id == sp_mkt.id, (
            f"mkt-intro must carry marketing space_id, got {mkt_item.space_id}"
        )
        assert mkt_item.org_id == org.id, f"mkt-intro must carry org_id, got {mkt_item.org_id}"
        # No collision: two separate items, different space_ids.
        assert eng_item.space_id != mkt_item.space_id, (
            "items from different spaces must have different space_ids"
        )


async def test_mirror_stamps_org_id_on_chunks_and_links(tmp_path, sqlite_factory):
    """mirror_bundle stamps org_id on WikiChunk and WikiLink rows."""
    with sqlite_factory() as s:
        org = Organization(slug="default", name="Default")
        s.add(org)
        s.flush()
        space = Space(org_id=org.id, slug="engineering", name="Engineering")
        s.add(space)
        s.commit()

    bundle = OkfBundle(tmp_path)
    bundle.init()
    _write(bundle, "page-a", "concept", "Page A", "# Page A\n\nSee [[page-b]].")
    _write(bundle, "page-b", "concept", "Page B", "# Page B\n\nbody")

    with sqlite_factory() as s:
        sp = s.query(Space).filter_by(slug="engineering").one()
        await mirror_bundle(s, bundle, space=sp)

    with sqlite_factory() as s:
        org = s.query(Organization).filter_by(slug="default").one()
        sp = s.query(Space).filter_by(slug="engineering").one()

        # Chunks must carry org_id
        chunks = s.query(WikiChunk).all()
        assert chunks, "chunks must be created"
        for chunk in chunks:
            assert chunk.org_id == org.id, f"WikiChunk must carry org_id, got {chunk.org_id}"

        # Links must carry org_id
        links = s.query(WikiLink).filter_by(origin="explicit").all()
        assert links, "explicit links must be created"
        for link in links:
            assert link.org_id == org.id, f"WikiLink must carry org_id, got {link.org_id}"
