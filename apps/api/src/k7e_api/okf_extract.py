"""OKF ingest — pass 1: extract typed knowledge from a source (one LLM call).

Returns a structured view of the source: a summary plus the entities, concepts,
citations and references the LLM detected. Pass 2 (resolve + compose) turns this
into typed OKF pages with ``[[wikilinks]]``. This is the structured, validated
front half of the "two-pass hybrid" ingest — the deterministic resolve step then
matches these names against existing pages.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from k7e_api.llm_client import LLMClient
from k7e_api.okf import DOMAINS, coerce_domain


class ExtractedEntity(BaseModel):
    """A person, tool, or organization the source is about or mentions."""

    name: str
    kind: str = "concept"  # person | tool | org
    description: str = ""


class ExtractedConcept(BaseModel):
    """An idea, pattern, or theory the source introduces or discusses."""

    name: str
    description: str = ""


class OkfExtraction(BaseModel):
    """Structured extraction of one source — drives typed-page creation."""

    title: str
    slug: str
    summary: str
    tags: list[str] = Field(default_factory=list)
    domain: str | None = None  # governed classification; validated against DOMAINS
    entities: list[ExtractedEntity] = Field(default_factory=list)
    concepts: list[ExtractedConcept] = Field(default_factory=list)
    # Works/sources this document cites (external references).
    citations: list[str] = Field(default_factory=list)
    # Names of other already-known pages/sources this document refers to.
    references: list[str] = Field(default_factory=list)


EXTRACT_SYSTEM_PROMPT = (
    "You curate an engineering knowledge wiki in Open Knowledge Format. Read a "
    "source document and extract its structured knowledge so it can be turned "
    "into typed, cross-linked wiki pages. Identify the entities (people, tools, "
    "organizations), the concepts (ideas, patterns, theories), the citations "
    "(external works the source cites), and the references (other documents or "
    "entities the source mentions or builds on). Do not invent facts. Return "
    "strict JSON matching the OkfExtraction schema."
)


def build_extract_prompt(text: str) -> str:
    return (
        f"Source document:\n{text}\n\n"
        "Return a single JSON object with keys:\n"
        "  - title (string): concise page title\n"
        "  - slug (string): url-safe lowercase slug from the title\n"
        "  - summary (string): a one- or two-sentence summary\n"
        "  - tags (array of strings)\n"
        f"  - domain (string or null): the single best-fit domain from "
        f"{list(DOMAINS)}, or null if none clearly fits\n"
        "  - entities (array): {name, kind (person|tool|org), description}\n"
        "  - concepts (array): {name, description}\n"
        "  - citations (array of strings): external works the source cites\n"
        "  - references (array of strings): other documents/entities it mentions\n"
        "Return only the JSON object."
    )


async def extract_okf(client: LLMClient, text: str) -> OkfExtraction:
    """Run the extraction LLM call and return the validated result."""
    raw = await client.complete_json(
        system=EXTRACT_SYSTEM_PROMPT,
        user=build_extract_prompt(text),
        schema_name="OkfExtraction",
    )
    result = OkfExtraction.model_validate(raw)
    result.domain = coerce_domain(result.domain)
    return result
