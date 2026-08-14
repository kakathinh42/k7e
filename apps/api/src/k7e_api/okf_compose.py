"""OKF ingest — pass 2b: compose a page's Markdown body (LLM).

Writes the prose body for one page. The planned ``[[wikilinks]]`` are also
appended deterministically by the orchestrator (a ``## Related`` section), so
links are guaranteed regardless of the model; the LLM's job is concise,
faithful prose (and it may weave the links inline too). For an existing page it
is asked to merge the new facts in and note the change, preserving prior content.
"""

from __future__ import annotations

from k7e_api.llm_client import LLMClient

COMPOSE_SYSTEM_PROMPT = (
    "You write the Markdown body of one page in an Open Knowledge Format wiki. "
    "Follow every rule:\n"
    "- FAITHFUL: use ONLY the supplied description and facts. Never add outside "
    "knowledge, examples, or speculation. If little is known, write little — a "
    "one-sentence stub is correct when that is all the source supports.\n"
    "- STRUCTURED: open with a single sentence that defines the subject in third "
    "person, then the key points as short prose or a tight bullet list.\n"
    "- CONCISE: no filler, no marketing tone, no repetition of the title.\n"
    "- LINKS: cross-reference with [[wikilinks]] ONLY to pages in the supplied "
    "'Related pages' list. Never invent a link to any other page.\n"
    "- UPDATING: when an existing body is supplied, merge the new facts in, keep "
    "correct existing content, and do not duplicate.\n"
    'Return strict JSON: {"markdown_body": "..."} with no YAML frontmatter and '
    "no '## Related' section (that is added separately)."
)


def build_compose_prompt(
    *,
    page_type: str,
    title: str,
    description: str,
    facts: list[str],
    links: list[str],
    existing_body: str | None,
) -> str:
    facts_block = "\n".join(f"- {f}" for f in facts) or "(none)"
    links_block = ", ".join(f"[[{slug}]]" for slug in links) or "(none)"
    existing_block = (
        f"\n\nExisting page body to UPDATE (preserve + merge):\n{existing_body}"
        if existing_body
        else ""
    )
    return (
        f"Write the Markdown body for a {page_type} page titled '{title}'.\n"
        f"Description: {description or '(none)'}\n"
        f"Facts to include (use only these — do not add outside knowledge):\n"
        f"{facts_block}\n"
        f"Related pages — link with [[wikilinks]] ONLY to these, and only where "
        f"the text naturally mentions them: {links_block}"
        f"{existing_block}\n\n"
        'Return only JSON: {"markdown_body": "<the body in Markdown>"}.'
    )


async def compose_body(
    client: LLMClient,
    *,
    page_type: str,
    title: str,
    description: str,
    facts: list[str],
    links: list[str],
    existing_body: str | None = None,
) -> str:
    """Compose (or update) a page body; returns the Markdown string."""
    raw = await client.complete_json(
        system=COMPOSE_SYSTEM_PROMPT,
        user=build_compose_prompt(
            page_type=page_type,
            title=title,
            description=description,
            facts=facts,
            links=links,
            existing_body=existing_body,
        ),
        schema_name="OkfCompose",
    )
    return str(raw.get("markdown_body", "")).strip()
