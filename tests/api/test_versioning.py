"""Tests for k7e_api.versioning – Markdown versioning service.

TDD: tests written BEFORE implementation.

Uses an in-memory SQLite database so no PostgreSQL instance is required.
SQLite does not enforce deferred foreign-key cycles at CREATE TABLE time,
so the circular FK (knowledge_items.current_version_id -> knowledge_item_versions)
does not cause issues with Base.metadata.create_all().

Covers:
1. New interpretation creates KnowledgeItem and version 1.
2. Second interpretation with the same slug creates version 2.
3. Gate "publish" sets current_version_id and status "published".
4. Gate "review" creates a version but does NOT set current_version_id.
"""

import uuid

import pytest
from k7e_api.gate import GateOutcome
from k7e_api.interpretation import Citation, Interpretation
from k7e_api.models import Base, KnowledgeItem, KnowledgeItemVersion
from k7e_api.versioning import upsert_item_version
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_RAW_DOC_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_CITATION_RAW_DOC_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
_MODEL_ID = "test-model-v1"
_CREATED_BY = "test-user"


@pytest.fixture(scope="module")
def engine():
    """Create an in-memory SQLite engine and populate schema."""
    eng = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    """Provide a fresh, isolated database session for each test."""
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    sess = Session()
    yield sess
    sess.rollback()
    sess.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_interp(slug: str = "test-slug", confidence: float = 0.9) -> Interpretation:
    """Build a minimal valid Interpretation."""
    return Interpretation(
        title="Test Title",
        slug=slug,
        summary="A test summary.",
        markdown_body="# Test\n\nBody text.",
        confidence=confidence,
        citations=[Citation(raw_document_id=_CITATION_RAW_DOC_ID, quote="A relevant quote.")],
    )


def _publish_gate() -> GateOutcome:
    return GateOutcome(decision="publish", reasons=[])


def _review_gate() -> GateOutcome:
    return GateOutcome(decision="review", reasons=["low_confidence:0.4"])


def _reject_gate() -> GateOutcome:
    return GateOutcome(decision="reject", reasons=["missing_citations"])


# ---------------------------------------------------------------------------
# Test 1 – new interpretation creates KnowledgeItem and version 1
# ---------------------------------------------------------------------------


def test_new_slug_creates_item_and_version_1(session):
    """First call for a new slug creates a KnowledgeItem and a version with version_number=1."""
    interp = _make_interp(slug="brand-new-slug")

    version = upsert_item_version(
        session,
        interp=interp,
        raw_document_id=_RAW_DOC_ID,
        model_id=_MODEL_ID,
        gate=_review_gate(),  # use review so no publishing side-effects
        created_by=_CREATED_BY,
    )

    # Returned object should be a KnowledgeItemVersion
    assert isinstance(version, KnowledgeItemVersion)

    # version_number must be 1 for a brand-new slug
    assert version.version_number == 1

    # KnowledgeItem must have been created
    item = session.get(KnowledgeItem, version.item_id)
    assert item is not None
    assert item.slug == "brand-new-slug"
    assert item.title == interp.title

    # Exactly one version should exist for this item
    assert len(item.versions) == 1


# ---------------------------------------------------------------------------
# Test 2 – second interpretation with same slug creates version 2
# ---------------------------------------------------------------------------


def test_same_slug_creates_version_2(session):
    """Second call with the same slug increments version_number to 2."""
    slug = "repeated-slug"
    interp = _make_interp(slug=slug)

    v1 = upsert_item_version(
        session,
        interp=interp,
        raw_document_id=_RAW_DOC_ID,
        model_id=_MODEL_ID,
        gate=_review_gate(),
        created_by=_CREATED_BY,
    )

    v2 = upsert_item_version(
        session,
        interp=interp,
        raw_document_id=_RAW_DOC_ID,
        model_id=_MODEL_ID,
        gate=_review_gate(),
        created_by=_CREATED_BY,
    )

    assert v1.version_number == 1
    assert v2.version_number == 2

    # item_id should be the same
    assert v1.item_id == v2.item_id

    # Item should have 2 versions now
    item = session.get(KnowledgeItem, v1.item_id)
    assert len(item.versions) == 2


# ---------------------------------------------------------------------------
# Test 3 – Gate "publish" sets current_version_id and status "published"
# ---------------------------------------------------------------------------


def test_publish_gate_sets_current_version_and_published_status(session):
    """When gate.decision == 'publish', item.current_version_id and status must be updated."""
    interp = _make_interp(slug="publish-slug")

    version = upsert_item_version(
        session,
        interp=interp,
        raw_document_id=_RAW_DOC_ID,
        model_id=_MODEL_ID,
        gate=_publish_gate(),
        created_by=_CREATED_BY,
    )

    item = session.get(KnowledgeItem, version.item_id)
    assert item.status == "published"
    assert item.current_version_id == version.id


# ---------------------------------------------------------------------------
# Test 4 – Gate "review" creates version but does NOT publish
# ---------------------------------------------------------------------------


def test_review_gate_does_not_set_current_version_id(session):
    """When gate.decision is 'review', current_version_id must remain None and status != 'published'."""
    interp = _make_interp(slug="review-only-slug")

    version = upsert_item_version(
        session,
        interp=interp,
        raw_document_id=_RAW_DOC_ID,
        model_id=_MODEL_ID,
        gate=_review_gate(),
        created_by=_CREATED_BY,
    )

    # Version IS created
    assert isinstance(version, KnowledgeItemVersion)

    item = session.get(KnowledgeItem, version.item_id)
    # status must not be "published"
    assert item.status != "published"
    # current_version_id must remain None (unchanged from initial state)
    assert item.current_version_id is None


# ---------------------------------------------------------------------------
# Test 5 – Gate "reject" also does not publish
# ---------------------------------------------------------------------------


def test_reject_gate_does_not_set_current_version_id(session):
    """When gate.decision is 'reject', current_version_id must remain None and status != 'published'."""
    interp = _make_interp(slug="reject-only-slug")

    version = upsert_item_version(
        session,
        interp=interp,
        raw_document_id=_RAW_DOC_ID,
        model_id=_MODEL_ID,
        gate=_reject_gate(),
        created_by=_CREATED_BY,
    )

    assert isinstance(version, KnowledgeItemVersion)

    item = session.get(KnowledgeItem, version.item_id)
    assert item.status != "published"
    assert item.current_version_id is None


# ---------------------------------------------------------------------------
# Test 6 – Citations are stored as JSON-serializable list
# ---------------------------------------------------------------------------


def test_citations_stored_as_json_list(session):
    """Citations from Interpretation are stored as a list of dicts in the version."""
    interp = _make_interp(slug="citations-slug")

    version = upsert_item_version(
        session,
        interp=interp,
        raw_document_id=_RAW_DOC_ID,
        model_id=_MODEL_ID,
        gate=_review_gate(),
        created_by=_CREATED_BY,
    )

    assert version.citations is not None
    assert isinstance(version.citations, list)
    assert len(version.citations) == 1
    # Each citation should be a dict (JSON-serializable), not a Pydantic model
    cit = version.citations[0]
    assert isinstance(cit, dict)
    assert "raw_document_id" in cit
    assert "quote" in cit
    assert cit["quote"] == "A relevant quote."


# ---------------------------------------------------------------------------
# Test 7 – model_id and created_by are stored correctly
# ---------------------------------------------------------------------------


def test_model_id_and_created_by_stored(session):
    """version.model_id and version.created_by must match what was passed in."""
    interp = _make_interp(slug="meta-slug")

    version = upsert_item_version(
        session,
        interp=interp,
        raw_document_id=_RAW_DOC_ID,
        model_id="specific-model-xyz",
        gate=_review_gate(),
        created_by="specific-user-abc",
    )

    assert version.model_id == "specific-model-xyz"
    assert version.created_by == "specific-user-abc"


# ---------------------------------------------------------------------------
# Test 8 – markdown_body is stored correctly
# ---------------------------------------------------------------------------


def test_markdown_body_stored(session):
    """version.markdown_body must match interp.markdown_body."""
    interp = Interpretation(
        title="Markdown Test",
        slug="markdown-body-slug",
        summary="Summary.",
        markdown_body="## Custom Markdown\n\nSpecific content here.",
        confidence=0.9,
        citations=[Citation(raw_document_id=_CITATION_RAW_DOC_ID, quote="quote")],
    )

    version = upsert_item_version(
        session,
        interp=interp,
        raw_document_id=_RAW_DOC_ID,
        model_id=_MODEL_ID,
        gate=_review_gate(),
        created_by=_CREATED_BY,
    )

    assert version.markdown_body == "## Custom Markdown\n\nSpecific content here."


# ---------------------------------------------------------------------------
# Test 9 – title is updated on subsequent calls
# ---------------------------------------------------------------------------


def test_item_title_updated_on_second_call(session):
    """If the title changes on a subsequent call for the same slug, the item title is updated."""
    slug = "title-update-slug"

    interp_v1 = Interpretation(
        title="Original Title",
        slug=slug,
        summary="Summary.",
        markdown_body="Body v1.",
        confidence=0.9,
        citations=[Citation(raw_document_id=_CITATION_RAW_DOC_ID, quote="quote")],
    )
    v1 = upsert_item_version(
        session,
        interp=interp_v1,
        raw_document_id=_RAW_DOC_ID,
        model_id=_MODEL_ID,
        gate=_review_gate(),
        created_by=_CREATED_BY,
    )

    interp_v2 = Interpretation(
        title="Updated Title",
        slug=slug,
        summary="Summary v2.",
        markdown_body="Body v2.",
        confidence=0.9,
        citations=[Citation(raw_document_id=_CITATION_RAW_DOC_ID, quote="quote2")],
    )
    upsert_item_version(
        session,
        interp=interp_v2,
        raw_document_id=_RAW_DOC_ID,
        model_id=_MODEL_ID,
        gate=_review_gate(),
        created_by=_CREATED_BY,
    )

    item = session.get(KnowledgeItem, v1.item_id)
    assert item.title == "Updated Title"


# ---------------------------------------------------------------------------
# Test 10 – a review-gated update must NOT mutate an already-published item
# ---------------------------------------------------------------------------


def test_published_item_not_mutated_by_review_version(session):
    """A review-gated update to an ALREADY-PUBLISHED item must not change the live
    title, updated_at, or current_version_id; the new version is pending_review."""
    slug = "live-page-slug"
    interp_v1 = _make_interp(slug=slug)
    interp_v1.title = "Live Title"
    v1 = upsert_item_version(
        session,
        interp=interp_v1,
        raw_document_id=_RAW_DOC_ID,
        model_id=_MODEL_ID,
        gate=_publish_gate(),
        created_by=_CREATED_BY,
    )
    item = session.get(KnowledgeItem, v1.item_id)
    assert item.status == "published"
    assert item.current_version_id == v1.id
    live_title = item.title
    live_updated = item.updated_at

    interp_v2 = _make_interp(slug=slug)
    interp_v2.title = "Proposed New Title"
    v2 = upsert_item_version(
        session,
        interp=interp_v2,
        raw_document_id=_RAW_DOC_ID,
        model_id=_MODEL_ID,
        gate=_review_gate(),
        created_by=_CREATED_BY,
    )

    item = session.get(KnowledgeItem, v1.item_id)
    # Live page is untouched
    assert item.title == live_title
    assert item.updated_at == live_updated
    assert item.current_version_id == v1.id
    # The new version is pending and snapshots its own proposed title
    assert v2.status == "pending_review"
    assert v2.title == "Proposed New Title"
    # The live version stays published
    assert session.get(KnowledgeItemVersion, v1.id).status == "published"


# ---------------------------------------------------------------------------
# Test 11 – explicit target_item (from source identity) overrides slug lookup
# ---------------------------------------------------------------------------


def test_upsert_uses_explicit_target_item_over_slug(session):
    """When target_item is given, the new version attaches to it even if the
    interp.slug differs (deterministic source identity overrides the LLM slug)."""
    first = _make_interp(slug="canonical-slug")
    v1 = upsert_item_version(
        session,
        interp=first,
        raw_document_id=_RAW_DOC_ID,
        model_id=_MODEL_ID,
        gate=_publish_gate(),
        created_by=_CREATED_BY,
    )
    item = session.get(KnowledgeItem, v1.item_id)

    # New ingest of the same source produces a different LLM slug, but we pass
    # the resolved target_item, so it must attach to the SAME item.
    second = _make_interp(slug="llm-drifted-different-slug")
    v2 = upsert_item_version(
        session,
        interp=second,
        raw_document_id=_RAW_DOC_ID,
        model_id=_MODEL_ID,
        gate=_review_gate(),
        created_by=_CREATED_BY,
        target_item=item,
    )
    assert v2.item_id == item.id

    from sqlalchemy import func
    from sqlalchemy import select as _select

    count = session.execute(
        _select(func.count())
        .select_from(KnowledgeItem)
        .where(KnowledgeItem.slug == "llm-drifted-different-slug")
    ).scalar_one()
    assert count == 0
