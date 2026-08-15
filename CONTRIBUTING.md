# Contributing to k7e

Thanks for your interest in contributing! k7e is an engineering knowledge
compiler: it ingests raw sources, compiles them with an LLM into citation-backed
Markdown wiki pages, and serves permission-aware retrieval. This guide gets a
change from your fork to a merged PR.

## Quick start (local development)

```bash
git clone https://github.com/kakathinh42/k7e.git
cd k7e
cp .env.example .env            # LOCAL DEVELOPMENT ONLY defaults
uv sync                         # installs api + worker + mcp + dev tools (uses uv.lock)
cd apps/web && npm ci && cd ..  # web app deps
```

Run the stack:

```bash
docker compose up --build       # postgres, temporal, litellm, api, worker, web, mcp
```

> The zero-credential demo (`make demo`) runs the whole pipeline offline with a
> stub LLM — no gateway key required. See `docs/getting-started/quickstart-offline.md`.

## Development commands

| Task | Command |
| --- | --- |
| Install everything | `uv sync` |
| Python tests (no DB/Temporal) | `uv run pytest -k "not pg and not temporal and not bench"` |
| Full Python tests | `uv run pytest` (needs Postgres + Temporal; see CI) |
| Lint + format | `uv run ruff check apps tests && uv run ruff format apps tests` |
| Web type-check + build | `cd apps/web && npm run build` |
| Web tests | `cd apps/web && npm test` |
| Run a service directly | API: `cd apps/api && uv run uvicorn k7e_api.main:app` |

A `Makefile` wraps the common commands (`make test`, `make lint`, `make demo`).

## How to contribute

1. **Open an issue first** for anything beyond a small fix — discuss the approach
   before investing in code.
2. Fork the repo and create a branch from `main`.
3. Make your change. Follow existing patterns; keep changes focused.
4. Add or update tests. We require tests for behavior changes.
5. Make sure everything is green:
   ```bash
   uv run ruff check apps tests && uv run ruff format --check apps tests
   uv run pytest -k "not pg and not temporal and not bench"
   cd apps/web && npm run build && npm test
   ```
6. Commit with [Conventional Commits](https://www.conventionalcommits.org/)
   (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`, `ci:`).
7. Open a PR against `main`. Fill in the PR template. Link the issue.

## Code style

- Python: ruff (line length 99). Tests may relax some lints (see `pyproject.toml`).
- TypeScript: strict (`tsc --noEmit` runs in `npm run build`).
- No commented-out code. No dead code. Names describe *what*, not *how*.

## Architecture orientation

Read [`docs/architecture/overview.md`](docs/architecture/overview.md) (or the
top-level `ARCHITECTURE.md`) before changes that cross the ingestion pipeline or
the permission-aware retrieval layer. The short version:

- **Canonical store** = a Git bundle of typed Markdown pages (OKF).
- **Runtime mirror** = Postgres (items, versions, chunks, link edges, RBAC) for
  search + graph. The mirror is rebuilt from the bundle.
- **Ingestion** = a Temporal workflow (`apps/worker`) that redacts → compiles
  (LLM) → mirrors. Deterministic checks gate the expensive LLM steps.
- **Retrieval** is filtered by the caller's permissions *before* content is returned.

## Reporting bugs and security issues

- Bugs and feature requests: [GitHub Issues](https://github.com/kakathinh42/k7e/issues).
- **Security vulnerabilities**: see [`SECURITY.md`](SECURITY.md) — do NOT open a
  public issue. Use a private vulnerability report.

## License

By contributing, you agree your contributions are licensed under the
[Apache License 2.0](LICENSE).
