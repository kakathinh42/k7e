"""Tests for Organization / Space / Project ORM models (Task 1 — M1 multi-org)."""

from __future__ import annotations

import pytest
from k7e_api.models import Organization, Project, Space
from sqlalchemy.exc import IntegrityError


def test_organization_create_and_read(sqlite_factory):
    """An Organization can be persisted and retrieved."""
    with sqlite_factory() as s:
        org = Organization(slug="acme", name="Acme Corp")
        s.add(org)
        s.flush()
        assert org.id is not None
        assert org.slug == "acme"
        assert org.name == "Acme Corp"
        assert org.settings is None
        assert org.created_at is not None


def test_space_belongs_to_org(sqlite_factory):
    """A Space can be created under an Organization."""
    with sqlite_factory() as s:
        org = Organization(slug="acme", name="Acme Corp")
        s.add(org)
        s.flush()

        space = Space(org_id=org.id, slug="eng", name="Engineering")
        s.add(space)
        s.flush()

        assert space.id is not None
        assert space.org_id == org.id
        assert space.slug == "eng"
        assert space.default_language == "en"
        assert space.okf_bundle_ref is None
        assert space.connector_config is None
        assert space.review_policy is None


def test_project_belongs_to_space(sqlite_factory):
    """A Project can be created under a Space."""
    with sqlite_factory() as s:
        org = Organization(slug="acme", name="Acme Corp")
        s.add(org)
        s.flush()

        space = Space(org_id=org.id, slug="eng", name="Engineering")
        s.add(space)
        s.flush()

        project = Project(space_id=space.id, slug="backend", name="Backend Team")
        s.add(project)
        s.flush()

        assert project.id is not None
        assert project.space_id == space.id
        assert project.slug == "backend"
        assert project.name == "Backend Team"


def test_org_space_project_hierarchy(sqlite_factory):
    """Full hierarchy: Organization → Space → Project."""
    with sqlite_factory() as s:
        org = Organization(slug="acme", name="Acme Corp", settings={"tier": "enterprise"})
        s.add(org)
        s.flush()

        space = Space(
            org_id=org.id,
            slug="product",
            name="Product Team",
            default_language="ja",
            review_policy={"require_approval": True},
        )
        s.add(space)
        s.flush()

        project = Project(space_id=space.id, slug="roadmap", name="Roadmap")
        s.add(project)
        s.commit()

        # Verify scalar reads
        s.expire_all()
        assert org.settings == {"tier": "enterprise"}
        assert space.default_language == "ja"
        assert space.review_policy == {"require_approval": True}
        assert project.slug == "roadmap"


def test_space_slug_unique_per_org(sqlite_factory):
    """Two Spaces with the same slug under the SAME org violates the unique constraint."""
    with sqlite_factory() as s:
        org = Organization(slug="acme", name="Acme Corp")
        s.add(org)
        s.flush()

        s.add(Space(org_id=org.id, slug="eng", name="Engineering"))
        s.flush()

        s.add(Space(org_id=org.id, slug="eng", name="Engineering Duplicate"))
        with pytest.raises(IntegrityError):
            s.flush()


def test_space_slug_unique_per_org_allows_same_slug_different_orgs(sqlite_factory):
    """Two Spaces with the same slug under DIFFERENT orgs is allowed."""
    with sqlite_factory() as s:
        org_a = Organization(slug="acme", name="Acme Corp")
        org_b = Organization(slug="globex", name="Globex Corp")
        s.add_all([org_a, org_b])
        s.flush()

        space_a = Space(org_id=org_a.id, slug="eng", name="Engineering A")
        space_b = Space(org_id=org_b.id, slug="eng", name="Engineering B")
        s.add_all([space_a, space_b])
        s.flush()  # should NOT raise

        assert space_a.org_id != space_b.org_id
        assert space_a.slug == space_b.slug


def test_project_slug_unique_per_space(sqlite_factory):
    """Two Projects with the same slug under the SAME space violates the unique constraint."""
    with sqlite_factory() as s:
        org = Organization(slug="acme", name="Acme Corp")
        s.add(org)
        s.flush()

        space = Space(org_id=org.id, slug="eng", name="Engineering")
        s.add(space)
        s.flush()

        s.add(Project(space_id=space.id, slug="backend", name="Backend"))
        s.flush()

        s.add(Project(space_id=space.id, slug="backend", name="Backend Duplicate"))
        with pytest.raises(IntegrityError):
            s.flush()


def test_project_slug_allows_same_slug_different_spaces(sqlite_factory):
    """Two Projects with the same slug under DIFFERENT spaces is allowed."""
    with sqlite_factory() as s:
        org = Organization(slug="acme", name="Acme Corp")
        s.add(org)
        s.flush()

        space_a = Space(org_id=org.id, slug="eng", name="Engineering")
        space_b = Space(org_id=org.id, slug="product", name="Product")
        s.add_all([space_a, space_b])
        s.flush()

        proj_a = Project(space_id=space_a.id, slug="backend", name="Backend in Eng")
        proj_b = Project(space_id=space_b.id, slug="backend", name="Backend in Product")
        s.add_all([proj_a, proj_b])
        s.flush()  # should NOT raise

        assert proj_a.space_id != proj_b.space_id
        assert proj_a.slug == proj_b.slug


def test_org_slug_is_globally_unique(sqlite_factory):
    """Organization.slug is globally unique."""
    with sqlite_factory() as s:
        s.add(Organization(slug="acme", name="Acme Corp"))
        s.flush()

        s.add(Organization(slug="acme", name="Another Acme"))
        with pytest.raises(IntegrityError):
            s.flush()
