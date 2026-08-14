# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**k7e** is an engineering knowledge compiler: it ingests raw company sources (internal wiki, Confluence, Jira, chat-agent conversations, meeting notes), compiles them via an LLM into reviewed, citation-backed Markdown wiki pages, and serves **permission-aware** retrieval to downstream consumers (`chat-agent`). The design principle throughout: pay the synthesis cost once at ingest time so retrieval reads few tokens. See `ARCHITECTURE.md` for the current architecture (and `ROADMAP.md` for what's next).

## Monorepo layout

Three deployable apps under `apps/`, orchestrated by `docker-compose.yml`:

- `apps/api` — FastAPI service (`k7e_api`). HTTP surface + DB/Alembic + LLM client + Temporal client. Also acts as a **shared library**.
- `apps/worker` — Temporal worker (`k7e_worker`). Runs the ingestion pipeline. Depends on `apps/api` as a package.
- `apps/web` — React 19 + Vite + TypeScript SPA (TanStack Query, React Router).

## Commands

**Run the full stack** (Postgres, Temporal, LiteLLM, api, worker, web):
```bash
cp .env.example .env     # then set LLM_GATEWAY_KEY for real LLM calls
docker compose up --build
```

**Python tests** (run from repo root; `pytest.ini` sets `asyncio_mode=auto`):
```bash
uv pip install -e "apps/api[dev]" -e apps/worker   # one-time env setup
pytest                                              # all tests under tests/
pytest tests/api/test_gate.py                       # one file
pytest tests/api/test_health.py::test_healthz_ok    # one test
```

**Web** (from `apps/web`):
```bash
npm install        # or `npm ci` (package-lock.json is committed)
npm test           # vitest run (non-watch)
npm run dev        # Vite dev server
npm run build      # tsc --noEmit (type-check) && vite build
```

**Lint / format** (ruff is installed as a global uv tool; a PostToolUse hook also auto-formats `.py` files after edits):
```bash
ruff check apps tests
ruff format apps tests
```

**Database migrations** (run from `apps/api`; or use the `/create-migration` skill):
```bash
cd apps/api && alembic revision --autogenerate -m "summary"
cd apps/api && alembic upgrade head
```

**End-to-end smoke** (stack must be up): `docker compose up -d && bash scripts/e2e_smoke.sh`

**Run a service directly** (outside compose): API = `cd apps/api && uvicorn k7e_api.main:app`; worker = `python -m k7e_worker.main`.

## Architecture

### Ingestion pipeline (the core flow)
Ingestion is a **Temporal workflow**, `IngestWorkflow` in `apps/worker/src/k7e_worker/workflows.py`, registered on the `wiki-ingest` task queue (`INGEST_TASK_QUEUE` in `apps/api/src/k7e_api/temporal_client.py`). The API starts a workflow when a document is uploaded (`POST /ingest/upload` → `routers/ingest.py`); the worker executes these activities in order:

1. `load_raw_document` — fetch text + metadata from the object store. Binary uploads (PDF/PNG/JPEG, see `EXTRACTABLE_MIME` in `validation.py`) return `text=None, needs_extraction=True`.
2. `extract_document_text_activity` — only when `needs_extraction`: vision-transcribe the file to text (`extraction.py`; pypdfium2 rasterization + one `transcribe_image` call per page on the `wiki-vision` alias; 25 MiB / `MAX_PDF_PAGES` guardrails enforced at upload; originals stay in the object store, not served).
3. `redact_activity` — replace PII, returning redacted text + detected `categories`.
4. `okf_ingest_activity` — the LLM step (retry `maximum_attempts=5`); writes typed OKF pages + `[[wikilinks]]` into the OKF git bundle.
5. `okf_mirror_activity` — mirror the bundle into Postgres (items, versions, embedded chunks, link edges) for search + graph.

Activities live in `apps/worker/src/k7e_worker/activities.py`, `extract_activities.py`, and `okf_activities.py`, and reuse API modules (`redaction.py`, `extraction.py`, `okf_ingest.py`, `okf_mirror.py`, `models.py`, `llm_client.py`). The deliberate split — deterministic checks gate the expensive LLM steps — is the token-saving strategy from the architecture doc. (The v1 gate/review pipeline was removed in the v2 OKF cutover; see ARCHITECTURE.md.)

### API surface
`apps/api/src/k7e_api/main.py` mounts four routers — `/ingest`, `/items`, `/search`, `/review` — plus `/healthz` and `/metrics` (Prometheus via `prometheus-client`). Logging is structured (`structlog`, configured in `logging_setup.py`).

### LLM access
**All** model traffic goes through `LiteLLMClient.complete_json()` in `apps/api/src/k7e_api/llm_client.py` → LiteLLM proxy → OpenAI-compatible LLM gateway (OpenAI-compatible). `StubLLMClient` is the deterministic test double; depend on the `LLMClient` protocol so tests can inject it. Model names are logical LiteLLM aliases (a bare alias is prefixed `openai/`); the default is `WIKI_MODEL` (`wiki-default`). Add models in `deploy/litellm/litellm_config.yaml` — never hardcode provider endpoints. (The `/llm-client-conventions` skill captures this in full.)

### Storage
Hybrid by design: **Postgres** (SQLAlchemy 2 + Alembic) is the product runtime mirror — items, versions, review state, search; **object store** (filesystem at `OBJECT_STORE_PATH`, see `object_store.py`) holds immutable raw documents; compiled Markdown is the canonical knowledge artifact. Retrieval is meant to be filtered by user/group permissions *before* returning context.

## Conventions & gotchas

- **Temporal determinism**: workflow code (`workflows.py`) must not read config, do I/O, or use wall-clock/random — all of that belongs in activities. Note `persist_activity` resolves settings via `get_settings()` inside the activity, not the workflow. The `temporal-workflow-reviewer` subagent checks this.
- **Worker ↔ API coupling**: `apps/worker/pyproject.toml` depends on the API via `k7e-api @ file:///${PROJECT_ROOT}/apps/api` (a `uv`-expanded path dependency). Install with `uv`, and treat `k7e_api` as a shared library — don't duplicate its logic in the worker.
- **Activities are plain async functions** (`@activity.defn`) and can be called directly in unit tests without a Temporal runtime (see `tests/worker/`).
- **Ports differ between compose and direct runs**: `docker compose` publishes *shifted* host ports — API `8001`, web `5174`, LiteLLM `4001`, Temporal `7234`, Postgres `5435` — mapping to the services' native in-container ports (`8000`/`5173`/`4000`/`7233`/`5432`). The README's `localhost:8000`/`5173`/`4000` refer to running services directly, not via compose.
- **Secrets**: `LLM_GATEWAY_KEY` and DB creds live only in `.env` (gitignored). A PreToolUse hook blocks edits to `.env` (edit `.env.example` instead).

## Project Claude tooling (`.claude/`)

- Skills: `/create-migration` (Alembic revision + round-trip validation), `llm-client-conventions` (auto-loaded background knowledge for LLM code).
- Subagents: `migration-reviewer` (reversibility / data-loss / index review), `temporal-workflow-reviewer` (determinism review).
- Hooks: ruff auto-format on `.py` edits; `.env` edit guard.
- MCP servers (`.mcp.json`): `postgres` (read-only schema + EXPLAIN, needs the stack up on `localhost:5435`) and `temporal` (read-only workflow inspection, needs Temporal on `localhost:7234`).
