# k7e

[![CI](https://github.com/kakathinh42/k7e/actions/workflows/ci.yml/badge.svg)](https://github.com/kakathinh42/k7e/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org)
[![Node 20+](https://img.shields.io/badge/node-20+-green.svg)](https://nodejs.org)

**Knowledge that improves with every source.** It ingests your scattered
sources (wiki, tickets, chat, docs), compiles them *once* with an LLM into
citation-backed Markdown wiki pages, and serves compact, access-controlled
retrieval to people and agents — so every later question is answered from a
short, trusted page instead of re-reading mountains of raw text.

> Inspired by Andrej Karpathy's [LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).
> This is an independent, enterprise-oriented implementation; it is not affiliated
> with or endorsed by the original author.

---

## Why

Engineering knowledge is scattered and stale. When an AI tries to answer from
raw sources it reads too much, slowly and expensively. k7e does the
expensive synthesis **once, at ingest time**, then serves compact pages:

- **Pay once, query cheap.** Compilation happens at ingest; retrieval reads
  short compiled pages, not huge raw documents.
- **Permission-aware.** Every result is filtered to the caller's roles *before*
  content is returned. A synthesized page can never leak a restricted source.
- **Citation-backed & reviewable.** Pages keep their sources and history. The
  canonical store is plain Markdown in Git — auditable and portable.
- **Good search out of the box.** Blends keyword + semantic + freshness +
  graph-centrality; handles CJK text and degrades to keyword-only if embeddings
  are down.
- **No model lock-in.** All model traffic goes through an OpenAI-compatible
  gateway; swap models by config.

## Try it in 2 minutes (no API key)

The offline demo runs the **whole pipeline** — ingest → redact → compile →
mirror → search — against deterministic stub LLM/embedding clients. No gateway
key, no external service beyond Docker:

```bash
git clone https://github.com/kakathinh42/k7e.git
cd k7e
cp .env.example .env
make demo        # boots the stack, ingests a synthetic corpus, asserts the loop
```

See [`docs/getting-started/quickstart-offline.md`](docs/getting-started/quickstart-offline.md).

## Full stack (bring your own LLM gateway)

```bash
cp .env.example .env
# set LLM_GATEWAY_BASE_URL and LLM_GATEWAY_KEY for real LLM calls
docker compose up --build
```

`docker compose` publishes shifted host ports:

| Service | URL |
| --- | --- |
| API | http://localhost:8001/healthz |
| Web UI | http://localhost:5174 |
| LiteLLM proxy | http://localhost:4001 |
| MCP server | http://localhost:9100/mcp |

Running a service directly (outside compose) uses its native port (API `8000`,
web `5173`, LiteLLM `4000`). **The compose defaults are for local development
only** — see [`docs/operations/security-hardening.md`](docs/operations/security-hardening.md)
before exposing anything.

## How it works

```
raw sources → redact PII → LLM compiles wiki pages + [[wikilinks]] → mirror to a
(wiki, tickets,                 saved as Markdown in Git (canonical)    fast, searchable,
 chats, docs)                                                          permission-aware index
                                                                            │
                                            people & agents ◀──────────────┘  ask questions,
                                                                                   get short cited
                                                                                   answers they may see
```

- **Canonical store** = a Git bundle of typed Markdown pages (the "OKF" bundle).
- **Runtime mirror** = Postgres (items, versions, embedded chunks, link edges,
  RBAC) rebuilt from the bundle for search + graph.
- **Ingestion** = a Temporal workflow: deterministic checks gate the expensive
  LLM compile step; redaction, extraction, and embedding run as retryable
  activities.
- **Retrieval** is filtered by the caller's permissions *before* content is
  returned.

Full detail: [`ARCHITECTURE.md`](ARCHITECTURE.md) and
[`docs/architecture/overview.md`](docs/architecture/overview.md).

## The four apps

| App | Path | Role |
| --- | --- | --- |
| **api** | `apps/api` | FastAPI service: HTTP surface, DB/Alembic, LLM + Temporal client. Also a shared library. |
| **worker** | `apps/worker` | Temporal worker running the ingestion pipeline. |
| **web** | `apps/web` | React 19 + Vite + TypeScript SPA. |
| **mcp** | `apps/mcp` | MCP server exposing `search_wiki` / `get_wiki_page` / `list_wiki_spaces` / `save_to_wiki` to MCP clients. |

## Development

```bash
uv sync                                 # api + worker + mcp + dev tools
cd apps/web && npm ci && cd ..          # web deps
make test                               # the common test/lint surface
```

| Task | Command |
| --- | --- |
| Python tests (no DB/Temporal) | `uv run pytest -k "not pg and not temporal and not bench"` |
| Lint + format | `make lint` |
| Web build + tests | `cd apps/web && npm run build && npm test` |
| Run API directly | `cd apps/api && uv run uvicorn k7e_api.main:app` |

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the full workflow and
[`docs/`](docs/) for concepts, operations, and architecture.

## Documentation

- [Architecture](ARCHITECTURE.md) — pipeline, storage, search, permissions.
- [Quickstart: offline demo](docs/getting-started/quickstart-offline.md)
- [Quickstart: full stack](docs/getting-started/quickstart-gateway.md)
- [Configuration](docs/getting-started/configuration.md)
- [Operations / security hardening](docs/operations/security-hardening.md)
- [Roadmap](ROADMAP.md)

## Security

The compose stack and `.env.example` defaults are **local development only**.
Read [`SECURITY.md`](SECURITY.md) and
[`docs/operations/security-hardening.md`](docs/operations/security-hardening.md)
before any real deployment. Source content is sent to your configured LLM
gateway during ingestion — ensure your provider's data-handling is acceptable.

## Contributing

Issues and PRs welcome! Read [`CONTRIBUTING.md`](CONTRIBUTING.md) first. For
security issues, use a [private report](SECURITY.md) — not a public issue.

## License

[Apache License 2.0](LICENSE). Third-party notices and attribution in
[`NOTICE`](NOTICE).
