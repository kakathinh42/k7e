# Quickstart: full stack (bring your own LLM gateway)

Real LLM compilation against any OpenAI-compatible gateway.

## 1. Configure

```bash
cp .env.example .env
```

Edit `.env`:

```ini
LLM_GATEWAY_BASE_URL=https://api.openai.com/v1   # any OpenAI-compatible endpoint
LLM_GATEWAY_KEY=sk-...                            # your key
LITELLM_MASTER_KEY=sk-local                       # rotates per environment
```

Optional Claude path: set `WIKI_MODEL=wiki-anthropic` plus
`LLM_ANTHROPIC_BASE_URL` / `LLM_ANTHROPIC_KEY` (see `deploy/litellm/litellm_config.yaml`).

## 2. Boot

```bash
docker compose up --build
```

| Service | URL |
| --- | --- |
| API health | http://localhost:8001/healthz |
| API ready  | http://localhost:8001/readyz |
| Web UI     | http://localhost:5174 |
| LiteLLM    | http://localhost:4001 |
| MCP server | http://localhost:9100/mcp |

> Compose publishes **shifted** host ports to avoid clashes. Running a service
> directly uses its native port (API `8000`, web `5173`, LiteLLM `4000`).

## 3. Web login

By default the web UI runs in `dev` auth mode (no login; a fixed dev identity).
For real login, set `VITE_AUTH_MODE=password` and rebuild the web image: the app
shows an email + password form (registration gated to `registration_allowed_domain`,
default `example.com`). Programmatic access (e.g. an MCP client) uses a
**Personal Access Token** (`wpat_…`, generated on the Tokens page) sent as
`Authorization: Bearer <token>`.

## 4. Ingest + search

Upload a document in the web UI (or `POST /ingest/upload`); the worker compiles
it into wiki pages. Search from the UI, the API (`GET /search?q=…`), or the MCP
server. See [configuration.md](configuration.md) for all knobs.

## Local development defaults are NOT production-safe

See [../operations/security-hardening.md](../operations/security-hardening.md)
before exposing any port.
