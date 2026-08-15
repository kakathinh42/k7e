"""Backfill script: stamp allowed_groups=["user:<owner>"] on null-ACL personal items.

Remediates rows created before the mirror stamped personal-space ACLs (the
cross-user leak fix in okf_mirror.py). Covers: a null-ACL personal item gets
stamped, an already-stamped personal item is left unchanged, a non-personal
item with a null ACL stays null (not touched), the function returns the
count of rows updated, and a second run is idempotent (updates 0).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from k7e_api.models import KnowledgeItem, KnowledgeItemVersion, Space
from sqlalchemy.orm import Session

from scripts.backfill_personal_acl import backfill

_TEST_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _publish(
    session: Session,
    *,
    slug: str,
    allowed_groups: list[str] | None,
    space_id: uuid.UUID | None = None,
) -> KnowledgeItem:
    """Seed a published source item; org_id is defaulted by the conftest hook."""
    item = KnowledgeItem(
        slug=slug,
        title=slug,
        status="published",
        type="source",
        allowed_groups=allowed_groups,
        space_id=space_id,
        provenance={"resource": None, "source_pages": []},
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(item)
    session.flush()
    version = KnowledgeItemVersion(
        item_id=item.id,
        version_number=1,
        markdown_body=f"# {slug}\n\nbody",
        model_id="t",
        created_by="t",
        citations=[],
        status="published",
        title=slug,
        created_at=_now(),
    )
    session.add(version)
    session.flush()
    item.current_version_id = version.id
    return item


def _make_personal_space(session: Session, *, owner_user_id: str, slug: str) -> Space:
    space = Space(
        org_id=_TEST_ORG_ID,
        slug=slug,
        name=slug,
        owner_user_id=owner_user_id,
    )
    session.add(space)
    session.flush()
    return space


class TestBackfillPersonalAcl:
    def test_null_acl_personal_item_gets_stamped(self, sqlite_factory):
        with sqlite_factory() as s:
            space = _make_personal_space(s, owner_user_id="alice", slug="alice-personal")
            item = _publish(s, slug="leaked-item", allowed_groups=None, space_id=space.id)
            s.commit()

            n = backfill(s)

            s.refresh(item)
            assert item.allowed_groups == ["user:alice"]
            assert n == 1

    def test_already_stamped_personal_item_unchanged(self, sqlite_factory):
        with sqlite_factory() as s:
            space = _make_personal_space(s, owner_user_id="alice", slug="alice-personal")
            item = _publish(
                s,
                slug="already-stamped",
                allowed_groups=["user:alice"],
                space_id=space.id,
            )
            s.commit()

            n = backfill(s)

            s.refresh(item)
            assert item.allowed_groups == ["user:alice"]
            assert n == 0

    def test_non_personal_null_acl_item_stays_null(self, sqlite_factory):
        with sqlite_factory() as s:
            item = _publish(s, slug="team-item", allowed_groups=None, space_id=None)
            s.commit()

            n = backfill(s)

            s.refresh(item)
            assert item.allowed_groups is None
            assert n == 0

    def test_mixed_batch_returns_count_of_updated_rows(self, sqlite_factory):
        with sqlite_factory() as s:
            space = _make_personal_space(s, owner_user_id="alice", slug="alice-personal")
            leaked = _publish(s, slug="leaked-item", allowed_groups=None, space_id=space.id)
            stamped = _publish(
                s,
                slug="already-stamped",
                allowed_groups=["user:alice"],
                space_id=space.id,
            )
            non_personal = _publish(s, slug="team-item", allowed_groups=None, space_id=None)
            s.commit()

            n = backfill(s)

            s.refresh(leaked)
            s.refresh(stamped)
            s.refresh(non_personal)
            assert n == 1
            assert leaked.allowed_groups == ["user:alice"]
            assert stamped.allowed_groups == ["user:alice"]
            assert non_personal.allowed_groups is None

    def test_idempotent_second_run_updates_zero(self, sqlite_factory):
        with sqlite_factory() as s:
            space = _make_personal_space(s, owner_user_id="alice", slug="alice-personal")
            _publish(s, slug="leaked-item", allowed_groups=None, space_id=space.id)
            s.commit()

            first = backfill(s)
            second = backfill(s)

            assert first == 1
            assert second == 0
