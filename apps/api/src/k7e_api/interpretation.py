"""Interpretation schema — structured output types for a compiled wiki entry.

Retained as plumbing for ``versioning.upsert_item_version`` (which writes a
version from an ``Interpretation``) and the read-path tests that seed data
through it. The v1 interpret *step* (the LLM prompt + activity) was removed in
the v2 OKF cutover; only the data types remain.
"""

from uuid import UUID

from pydantic import BaseModel, Field


class Citation(BaseModel):
    """A citation linking an interpretation claim back to a source document."""

    raw_document_id: UUID
    quote: str


class Interpretation(BaseModel):
    """Structured wiki entry produced by the LLM from a raw source document."""

    title: str
    slug: str
    summary: str
    markdown_body: str
    tags: list[str] = []
    confidence: float = Field(ge=0.0, le=1.0)
    citations: list[Citation] = []
