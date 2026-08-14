"""Task 9 — space-routed worker pipeline: per-space OKF bundles + mirror.

Covers:
1. ``load_raw_document`` returns ``space_id``/``space_slug`` for a
   space-stamped RawDocument, and ``None``/``None`` for a legacy row.
2. ``okf_ingest_activity(space_slug=...)`` writes pages under
   ``<okf_bundles_root>/<slug>/`` and leaves the default bundle byte-identical
   (the privacy boundary between a personal space and the shared bundle).
3. ``okf_mirror_activity(space_id=...)`` mirrors items stamped with that
   space's ``org_id``/``space_id`` — and the legacy (``space_id=None``) path
   still resolves the default org's ``engineering`` space unchanged.
4. Confirming test: a personal RawDocument's ``allowed_groups`` already
   propagate onto the mirrored ``KnowledgeItem`` through the existing
   sha256-match mechanism in ``k7e_api.okf_mirror.mirror_bundle`` (the same
   path M3 team ingestion uses) — no space-specific mirror code needed.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from k7e_api.models import KnowledgeItem, Organization, RawDocument, Space
from k7e_api.okf import OkfFrontmatter, OkfPage
from k7e_api.okf_bundle import OkfBundle
from temporalio.exceptions import ApplicationError


def _unwrap(fn):
    """Return the underlying coroutine function for an @activity.defn function."""
    return getattr(fn, "fn", fn)


class _EchoLLMClient:
    """Deterministic client whose extraction echoes a caller-supplied marker.

    Unlike ``StubLLMClient`` (which returns a fixed canned entity regardless
    of input text), this client lets a test assert that document-specific
    content actually landed in the written OKF pages — needed for the
    bundle-isolation/privacy assertion below.
    """

    def __init__(self, marker: str) -> None:
        self._marker = marker
        self.usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "calls": 0,
        }

    async def complete_json(self, *, system, user, schema_name):
        self.usage["calls"] += 1
        if schema_name == "OkfExtraction":
            return {
                "title": self._marker,
                "slug": "personal-doc",
                "summary": f"Notes about {self._marker}.",
                "tags": [],
                "domain": None,
                "entities": [{"name": self._marker, "kind": "concept", "description": "x"}],
                "concepts": [],
                "citations": [],
                "references": [],
            }
        if schema_name == "OkfCompose":
            return {"markdown_body": f"## Overview\n\n{self._marker} details.\n"}
        if schema_name == "OkfRelate":
            return {"related": [], "aliases": {}}
        return {"contradiction": False, "explanation": ""}


# ---------------------------------------------------------------------------
# 1. load_raw_document
# ---------------------------------------------------------------------------


async def test_load_raw_document_returns_space_keys_for_space_stamped_row(
    sqlite_factory, tmp_path
):
    import k7e_worker.activities as mod

    obj_path = tmp_path / "doc.md"
    obj_path.write_text("hello alice", encoding="utf-8")

    with sqlite_factory() as session:
        org = Organization(slug="o", name="O")
        session.add(org)
        session.flush()
        space = Space(org_id=org.id, slug="user-alice", name="Personal", owner_user_id="alice")
        session.add(space)
        session.flush()
        raw = RawDocument(
            filename="doc.md",
            sha256="a" * 64,
            object_store_ref=str(obj_path),
            mime_type="text/markdown",
            size_bytes=len(b"hello alice"),
            space_id=space.id,
            created_by="alice",
        )
        legacy_raw = RawDocument(
            filename="legacy.md",
            sha256="b" * 64,
            object_store_ref=str(obj_path),
            mime_type="text/markdown",
            size_bytes=len(b"hello alice"),
        )
        session.add_all([raw, legacy_raw])
        session.commit()
        raw_id, legacy_id, space_id = str(raw.id), str(legacy_raw.id), str(space.id)

    mod.session_factory = sqlite_factory
    fn = _unwrap(mod.load_raw_document)

    result = await fn(raw_id)
    assert result["space_id"] == space_id
    assert result["space_slug"] == "user-alice"

    legacy_result = await fn(legacy_id)
    assert legacy_result["space_id"] is None
    assert legacy_result["space_slug"] is None


# ---------------------------------------------------------------------------
# 2. okf_ingest_activity — per-space bundle + isolation from the default bundle
# ---------------------------------------------------------------------------


async def test_okf_ingest_activity_writes_under_space_bundle_and_isolates_default(
    tmp_path, sqlite_factory, monkeypatch
):
    import k7e_worker.okf_activities as mod

    bundles_root = tmp_path / "bundles"
    default_bundle_dir = tmp_path / "default-bundle"
    marker = "Zylatrex-Q7-Confidential"

    # Pre-seed the default bundle with unrelated content so "untouched" is a
    # meaningful, byte-identical-before/after assertion rather than "never
    # created".
    default_bundle = OkfBundle(default_bundle_dir)
    default_bundle.init()
    default_bundle.write_page(
        OkfPage(
            slug="unrelated",
            frontmatter=OkfFrontmatter(type="concept", title="Unrelated"),
            body="# Unrelated\n\nNothing to do with alice.",
        )
    )
    before = {
        p: p.read_text(encoding="utf-8") for p in default_bundle_dir.rglob("*") if p.is_file()
    }

    monkeypatch.setattr(mod, "session_factory", sqlite_factory)
    monkeypatch.setattr(
        mod,
        "get_settings",
        lambda: SimpleNamespace(
            okf_bundle_path=str(default_bundle_dir),
            okf_bundles_root=str(bundles_root),
            wiki_model="wiki-default",
        ),
    )
    monkeypatch.setattr(mod, "llm_client_factory", lambda: _EchoLLMClient(marker))

    fn = _unwrap(mod.okf_ingest_activity)
    result = await fn(
        f"Personal notes: {marker} is a secret project codename.",
        str(uuid.uuid4()),
        {"source_uri": "conv://alice/1"},
        "user-alice",
    )
    assert result["pages"]

    space_dir = bundles_root / "user-alice"
    assert space_dir.exists()
    space_files = [p for p in space_dir.rglob("*.md")]
    assert space_files, "expected pages under the space bundle"
    assert any(marker in p.read_text(encoding="utf-8") for p in space_files)

    # The privacy boundary: the default bundle must be byte-identical to
    # before this personal ingest ran, and must contain the marker nowhere.
    after = {
        p: p.read_text(encoding="utf-8") for p in default_bundle_dir.rglob("*") if p.is_file()
    }
    assert after == before
    assert not any(marker in content for content in after.values())


# ---------------------------------------------------------------------------
# 3. okf_mirror_activity — space-routed + legacy default path
# ---------------------------------------------------------------------------


async def test_okf_mirror_activity_stamps_space_id_from_space_bundle(
    tmp_path, sqlite_factory, monkeypatch
):
    import k7e_worker.okf_activities as mod

    bundles_root = tmp_path / "bundles"
    space_bundle = OkfBundle(bundles_root / "user-alice")
    space_bundle.init()
    space_bundle.write_page(
        OkfPage(
            slug="alice-note",
            frontmatter=OkfFrontmatter(type="source", title="Alice Note"),
            body="# Alice Note\n\nPersonal stuff.",
        )
    )

    with sqlite_factory() as session:
        org = Organization(slug="o", name="O")
        session.add(org)
        session.flush()
        space = Space(org_id=org.id, slug="user-alice", name="Personal", owner_user_id="alice")
        session.add(space)
        session.commit()
        space_id, org_id = str(space.id), org.id

    monkeypatch.setattr(mod, "session_factory", sqlite_factory)
    monkeypatch.setattr(
        mod,
        "get_settings",
        lambda: SimpleNamespace(
            okf_bundle_path=str(tmp_path / "default-bundle"),
            okf_bundles_root=str(bundles_root),
        ),
    )

    fn = _unwrap(mod.okf_mirror_activity)
    result = await fn(space_id, "user-alice")
    assert result["pages"] == 1

    with sqlite_factory() as session:
        item = session.query(KnowledgeItem).filter_by(slug="alice-note").one()
        assert str(item.space_id) == space_id
        assert item.org_id == org_id


async def test_okf_mirror_activity_legacy_default_space_path_unchanged(
    tmp_path, sqlite_factory, monkeypatch
):
    """space_id=None (legacy/unrouted) still resolves the default org's
    'engineering' space and mirrors the shared default bundle — regression
    lock for the pre-Task-9 behaviour."""
    import k7e_worker.okf_activities as mod

    default_bundle_dir = tmp_path / "default-bundle"
    default_bundle = OkfBundle(default_bundle_dir)
    default_bundle.init()
    default_bundle.write_page(
        OkfPage(
            slug="legacy-note",
            frontmatter=OkfFrontmatter(type="concept", title="Legacy"),
            body="# Legacy\n\nOld behavior.",
        )
    )

    with sqlite_factory() as session:
        org = Organization(slug="default", name="Default")
        session.add(org)
        session.flush()
        space = Space(org_id=org.id, slug="engineering", name="Engineering")
        session.add(space)
        session.commit()
        space_id, org_id = space.id, org.id

    monkeypatch.setattr(mod, "session_factory", sqlite_factory)
    monkeypatch.setattr(
        mod,
        "get_settings",
        lambda: SimpleNamespace(
            okf_bundle_path=str(default_bundle_dir),
            okf_bundles_root=str(tmp_path / "bundles"),
            default_org_slug="default",
        ),
    )

    fn = _unwrap(mod.okf_mirror_activity)
    result = await fn()  # space_id=None, space_slug=None — legacy call shape
    assert result["pages"] == 1

    with sqlite_factory() as session:
        item = session.query(KnowledgeItem).filter_by(slug="legacy-note").one()
        assert item.space_id == space_id
        assert item.org_id == org_id


async def test_okf_mirror_activity_unresolvable_space_id_fails_non_retryable(
    tmp_path, sqlite_factory, monkeypatch
):
    """A set-but-unresolvable space_id (space deleted mid-ingest / bug) must
    fail LOUD and non-retryable — mirroring the per-space bundle with
    space=None would write personal content with no org_id/space_id tenant
    stamps, breaching the privacy boundary. Assert it raises AND that no
    untenified KnowledgeItem is written as a side effect."""
    import k7e_worker.okf_activities as mod

    bundles_root = tmp_path / "bundles"
    space_bundle = OkfBundle(bundles_root / "user-alice")
    space_bundle.init()
    space_bundle.write_page(
        OkfPage(
            slug="alice-note",
            frontmatter=OkfFrontmatter(type="source", title="Alice Note"),
            body="# Alice Note\n\nPersonal stuff.",
        )
    )

    # A valid-format UUID with no matching Space row (nothing seeded here).
    missing_space_id = str(uuid.uuid4())

    monkeypatch.setattr(mod, "session_factory", sqlite_factory)
    monkeypatch.setattr(
        mod,
        "get_settings",
        lambda: SimpleNamespace(
            okf_bundle_path=str(tmp_path / "default-bundle"),
            okf_bundles_root=str(bundles_root),
        ),
    )

    fn = _unwrap(mod.okf_mirror_activity)
    with pytest.raises(ApplicationError) as ei:
        await fn(missing_space_id, "user-alice")
    assert ei.value.non_retryable is True
    assert missing_space_id in str(ei.value)

    # No item may have been written — the guard must fire BEFORE mirror_bundle.
    with sqlite_factory() as session:
        assert session.query(KnowledgeItem).count() == 0


# ---------------------------------------------------------------------------
# 4. Confirming test: allowed_groups propagation needs NO space-specific code
# ---------------------------------------------------------------------------


async def test_okf_mirror_activity_propagates_personal_allowed_groups(
    tmp_path, sqlite_factory, monkeypatch
):
    """A personal RawDocument's allowed_groups (['user:alice']) reach the
    mirrored KnowledgeItem through the SAME sha256-match mechanism M3 team
    ingestion already relies on (k7e_api.okf_mirror.mirror_bundle, matching
    RawDocument.sha256 == page.frontmatter.resource) — confirming that
    okf_mirror_activity needs no additional allowed_groups handling for
    space-routed sources."""
    import k7e_worker.okf_activities as mod

    bundles_root = tmp_path / "bundles"
    space_bundle = OkfBundle(bundles_root / "user-alice")
    space_bundle.init()
    space_bundle.write_page(
        OkfPage(
            slug="alice-note",
            frontmatter=OkfFrontmatter(type="source", title="Alice Note", resource="f" * 64),
            body="# Alice Note\n\nPersonal stuff.",
        )
    )

    with sqlite_factory() as session:
        org = Organization(slug="o", name="O")
        session.add(org)
        session.flush()
        space = Space(org_id=org.id, slug="user-alice", name="Personal", owner_user_id="alice")
        session.add(space)
        session.flush()
        raw = RawDocument(
            filename="conv.md",
            sha256="f" * 64,
            object_store_ref="x",
            mime_type="text/markdown",
            size_bytes=1,
            space_id=space.id,
            created_by="alice",
            allowed_groups=["user:alice"],
        )
        session.add(raw)
        session.commit()
        space_id = str(space.id)

    monkeypatch.setattr(mod, "session_factory", sqlite_factory)
    monkeypatch.setattr(
        mod,
        "get_settings",
        lambda: SimpleNamespace(
            okf_bundle_path=str(tmp_path / "default-bundle"),
            okf_bundles_root=str(bundles_root),
        ),
    )

    fn = _unwrap(mod.okf_mirror_activity)
    await fn(space_id, "user-alice")

    with sqlite_factory() as session:
        item = session.query(KnowledgeItem).filter_by(slug="alice-note").one()
        assert item.allowed_groups == ["user:alice"]
