"""Regression tests: personal-space pages must be stamped with the owner ACL.

Closes the cross-user leak where a conversation's ``source`` page has
``frontmatter.resource`` set to a thread id (not a sha256), so the old
sha256-match lookup against ``RawDocument`` always misses and leaves
``allowed_groups=None`` (treated as public by rbac). Personal-space pages —
source AND derived — must always carry ``["user:<owner>"]`` regardless of the
resource/RawDocument match.
"""

from __future__ import annotations

from k7e_api.models import KnowledgeItem, Organization, RawDocument, Space
from k7e_api.okf import OkfFrontmatter, OkfPage
from k7e_api.okf_bundle import OkfBundle
from k7e_api.okf_mirror import mirror_bundle


def _write(bundle, slug, ptype, title, body, resource=None, sources=None):
    bundle.write_page(
        OkfPage(
            slug=slug,
            frontmatter=OkfFrontmatter(
                type=ptype,
                title=title,
                resource=resource,
                sources=sources or [],
            ),
            body=body,
        )
    )


async def test_personal_space_source_with_thread_id_resource_gets_owner_acl(
    tmp_path, sqlite_factory
):
    """A conversation source page's resource is a thread-id, not a sha256 — no
    RawDocument ever matches it. In a personal space it must still be stamped
    with the owner's ACL instead of falling through to null/public."""
    with sqlite_factory() as s:
        org = Organization(slug="acme", name="Acme Corp")
        s.add(org)
        s.flush()
        space = Space(
            org_id=org.id,
            slug="personal-alice",
            name="Alice's Space",
            owner_user_id="alice",
        )
        s.add(space)
        s.commit()

    bundle = OkfBundle(tmp_path)
    bundle.init()
    _write(
        bundle,
        "conversation-isolation-proof",
        "source",
        "Conversation",
        "# Conversation\n\nbody",
        resource="isolation-proof-1783909860",  # thread id, NOT a sha256
    )

    with sqlite_factory() as s:
        sp = s.query(Space).filter_by(slug="personal-alice").one()
        await mirror_bundle(s, bundle, space=sp)

    with sqlite_factory() as s:
        item = s.query(KnowledgeItem).filter_by(slug="conversation-isolation-proof").one()
        assert item.allowed_groups == ["user:alice"]


async def test_personal_space_derived_page_gets_owner_acl(tmp_path, sqlite_factory):
    """A derived (non-source) page in a personal space must also be private to
    the owner — not left null the way derived pages are in org/team bundles."""
    with sqlite_factory() as s:
        org = Organization(slug="acme", name="Acme Corp")
        s.add(org)
        s.flush()
        space = Space(
            org_id=org.id,
            slug="personal-bob",
            name="Bob's Space",
            owner_user_id="bob",
        )
        s.add(space)
        s.commit()

    bundle = OkfBundle(tmp_path)
    bundle.init()
    _write(
        bundle,
        "bobs-source-thread",
        "source",
        "Bob Source",
        "# Bob Source\n\nbody",
        resource="thread-abc123",
    )
    _write(
        bundle,
        "bobs-concept",
        "concept",
        "Bob Concept",
        "# Bob Concept\n\nderived from the conversation",
        sources=["[[bobs-source-thread]]"],
    )

    with sqlite_factory() as s:
        sp = s.query(Space).filter_by(slug="personal-bob").one()
        await mirror_bundle(s, bundle, space=sp)

    with sqlite_factory() as s:
        source_item = s.query(KnowledgeItem).filter_by(slug="bobs-source-thread").one()
        derived_item = s.query(KnowledgeItem).filter_by(slug="bobs-concept").one()
        assert source_item.allowed_groups == ["user:bob"]
        assert derived_item.allowed_groups == ["user:bob"]


async def test_non_personal_bundle_keeps_existing_allowed_groups_behavior(
    tmp_path, sqlite_factory
):
    """A bundle mirrored with a non-personal (team/org) space, or no space at
    all, is unaffected: source inherits RawDocument.allowed_groups by sha256
    match, and derived pages stay null."""
    sha = "a" * 64
    with sqlite_factory() as s:
        org = Organization(slug="acme", name="Acme Corp")
        s.add(org)
        s.flush()
        team_space = Space(org_id=org.id, slug="engineering", name="Engineering")
        s.add(team_space)
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
    _write(
        bundle,
        "team-doc",
        "source",
        "Team Doc",
        "# Team Doc\n\nbody",
        resource=sha,
    )
    _write(
        bundle,
        "team-concept",
        "concept",
        "Team Concept",
        "# Team Concept\n\nderived",
        resource=sha,
        sources=["[[team-doc]]"],
    )

    with sqlite_factory() as s:
        sp = s.query(Space).filter_by(slug="engineering").one()
        await mirror_bundle(s, bundle, space=sp)

    with sqlite_factory() as s:
        source_item = s.query(KnowledgeItem).filter_by(slug="team-doc").one()
        derived_item = s.query(KnowledgeItem).filter_by(slug="team-concept").one()
        assert source_item.allowed_groups == ["finance"]
        assert derived_item.allowed_groups is None
