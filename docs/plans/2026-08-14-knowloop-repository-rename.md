# KnowLoop Repository Rename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename every project-owned llm-wiki identity to KnowLoop before the first public release while preserving HTTP, database, migration, and OKF compatibility.

**Architecture:** Rename Python distributions and import namespaces first so tests expose missed references. Then rename runtime surfaces (MCP commands, Compose services, Docker comments), web/project metadata, and public documentation. Regenerate lockfiles last and verify no obsolete identity remains outside the accepted ADR and LLM Wiki acknowledgement.

**Tech Stack:** Python 3.11+, uv workspace, FastAPI, Temporal, MCP SDK 1.x, React/Vite/TypeScript, Docker Compose, GitHub Actions.

## Global Constraints

- Public brand: `KnowLoop`.
- Repository: `knowloop`.
- Primary tagline: `Knowledge that improves with every source.`
- Developer tagline: `Ingest. Synthesize. Link. Repeat.`
- Python distributions: `knowloop-api`, `knowloop-worker`, `knowloop-mcp`.
- Python imports: `knowloop_api`, `knowloop_worker`, `knowloop_mcp`.
- Commands: `knowloop-mcp`, `knowloop-mcp-http`.
- No compatibility wrappers: this is pre-1.0 and not publicly released.
- Preserve HTTP routes, JSON fields, database tables/columns, Alembic revision IDs/order, OKF schema/frontmatter, wikilink syntax, and generic domain names such as `WIKI_MODEL` and `wiki_chunks`.
- Keep `LLM Wiki` only in attribution/context describing Karpathy's design pattern.

---

### Task 1: Rename Python packages and imports

**Files:**
- Move: `apps/api/src/wiki_api/` → `apps/api/src/knowloop_api/`
- Move: `apps/worker/src/wiki_worker/` → `apps/worker/src/knowloop_worker/`
- Move: `apps/mcp/src/wiki_mcp/` → `apps/mcp/src/knowloop_mcp/`
- Modify: all Python files under `apps/`, `tests/`, and `scripts/`
- Modify: `apps/api/alembic/env.py`, all three `pyproject.toml` files

- [ ] Rename directories with `git mv`.
- [ ] Replace import/module prefixes consistently.
- [ ] Rename distribution names and MCP entry points.
- [ ] Run `uv sync`, import smoke, Ruff, and Python test suite.

### Task 2: Rename runtime and deployment identity

**Files:**
- Modify: `docker-compose.yml`, `docker-compose.demo.yml`
- Modify: `apps/*/Dockerfile`, `Makefile`, `.mcp.json`, `scripts/*.sh`
- Modify: `.github/workflows/ci.yml`, `deploy/litellm/litellm_config.yaml`

- [ ] Rename repo-owned Compose services, container references, health text, and commands.
- [ ] Preserve API route/protocol names and generic wiki domain terminology.
- [ ] Validate both Compose files with `docker compose config` when Docker is available.

### Task 3: Rename web, docs, and community identity

**Files:**
- Modify: `apps/web/package.json`, `apps/web/package-lock.json`, `apps/web/index.html`, UI copy/tests
- Modify: `README.md`, `ARCHITECTURE.md`, `ROADMAP.md`, `CLAUDE.md`, `NOTICE`, governance files, docs
- Preserve: `docs/architecture/decisions/0001-knowloop-project-identity.md` as the accepted mapping record

- [ ] Apply KnowLoop product copy and canonical taglines.
- [ ] Change GitHub URLs to `kakathinh/knowloop` pending final org choice.
- [ ] Keep LLM Wiki only in the acknowledgement and ADR context.
- [ ] Run web build/tests.

### Task 4: Regenerate lockfiles and verify

**Files:**
- Regenerate: `uv.lock`, `apps/web/package-lock.json`

- [ ] Run `uv sync` and confirm only KnowLoop distributions/imports.
- [ ] Run `uv run ruff check apps tests` and `uv run ruff format --check apps tests`.
- [ ] Run Python non-service suite and web build/tests.
- [ ] Scan for forbidden project identities; adjudicate only generic wiki schema/domain terms and ADR/acknowledgement references.
- [ ] Confirm git status contains only intended rename changes.
