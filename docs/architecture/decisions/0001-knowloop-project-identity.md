# ADR 0001: Adopt KnowLoop as the project identity

**Status:** Superseded by the k7e rebrand (2026-08-14) — see commit `fdefb6f`  
**Date:** 2026-08-14

## Context

`llm-wiki` describes an architectural concept but is generic, difficult to own
in search, and weak as a memorable open-source brand. The project has evolved
into a permission-aware knowledge compiler: it transforms scattered source
material into durable, citation-backed Markdown and serves compact retrieval to
people and agents.

The name should communicate the central loop from Andrej Karpathy's LLM Wiki
pattern: ingest sources, synthesize and connect durable pages, query them, lint
for gaps and contradictions, then improve the knowledge artifact continuously.
Each source makes future retrieval and the existing knowledge graph more useful.

KnowLoop combines two immediately recognizable ideas:

- **Know** — durable organizational knowledge, not a generic chatbot.
- **Loop** — ingest → synthesize → link → query → lint → improve.

Preliminary collision screening found no matching npm or PyPI package, no exact
GitHub organization/repository, and no directly competing software product. An
academic paper uses “KnowLoop” for a human-in-the-loop conceptual-design
framework; this screening is not formal legal trademark clearance.

## Decision

Adopt **KnowLoop** as the public and internal project identity.

- Primary tagline: **Knowledge that improves with every source.**
- Developer tagline: **Ingest. Synthesize. Link. Repeat.**
- One-line description: **KnowLoop turns scattered company sources into a
  persistent, citation-backed, permission-aware knowledge layer for people and
  agents.**

Rename all project-owned identities before the first public release:

| Current | New |
| --- | --- |
| `llm-wiki` | `knowloop` |
| `llm-wiki-api` | `knowloop-api` |
| `llm-wiki-worker` | `knowloop-worker` |
| `llm-wiki-mcp` | `knowloop-mcp` |
| `llm-wiki-web` | `knowloop-web` |
| `wiki_api` | `knowloop_api` |
| `wiki_worker` | `knowloop_worker` |
| `wiki_mcp` | `knowloop_mcp` |
| `wiki-mcp` / `wiki-mcp-http` | `knowloop-mcp` / `knowloop-mcp-http` |
| Docker project/service references owned by this repo | KnowLoop equivalents |
| User-facing copy, badges, docs, package metadata, lock entries | KnowLoop equivalents |

The public repository will be `knowloop` under the final GitHub account or
organization. “LLM Wiki” remains only in acknowledgement text describing the
inspiration from Andrej Karpathy's design pattern.

## Compatibility boundary

This is a pre-1.0, not-yet-public project with no supported external package
consumers. Rename namespaces completely now; do not add `wiki_*` compatibility
wrappers.

Preserve stable product data and protocol surfaces that are not brand identity:

- HTTP route paths and JSON field names.
- Database table and column names.
- Existing Alembic revision IDs and migration ordering.
- Persisted OKF Markdown schema/frontmatter and wikilink syntax.
- Generic environment variables such as `WIKI_MODEL` where “wiki” describes the
  domain rather than the old product brand, unless a variable is explicitly a
  package/service identity.

## Brand character

KnowLoop should feel technical, durable, and continuously improving. Avoid
chatbot sparkle, robot mascots, and magical claims. Visual language should
suggest a loop of raw fragments becoming connected, trusted knowledge—possibly
forming a linked `K` or an open circular graph.

## Verification

The rename is complete when:

1. No project-owned `llm-wiki`, `wiki_api`, `wiki_worker`, `wiki_mcp`,
   `llm-wiki-*`, or `wiki-mcp*` identity remains outside acknowledgement,
   migration-history text that must remain stable, or generic domain language.
2. `uv sync --frozen`, Python imports, console entry points, Docker builds, web
   build/tests, and the offline demo use KnowLoop names.
3. Python tests, web tests, Ruff, and repository leak scans pass.
4. README badges and community links target the final KnowLoop repository.

## Consequences

The rename is broad and will change most imports and package metadata, producing
a large mechanical diff. Performing it before the first public release avoids a
long-term compatibility layer and gives the project a coherent, searchable
identity from day one.
