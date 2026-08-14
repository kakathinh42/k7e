# Configuration

All runtime configuration is environment-driven (Pydantic Settings in
`apps/api/src/k7e_api/config.py`). Copy `.env.example` to `.env` and edit.

## Core

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+psycopg://wiki:wiki@postgres:5432/wiki` | Postgres (pgvector) DSN. |
| `TEMPORAL_HOST` | `temporal:7233` | Temporal dev server address. |
| `OBJECT_STORE_PATH` | `/data/objects` | Immutable raw document store. |
| `OKF_BUNDLE_PATH` | `.data/okf-bundle` | Canonical Markdown bundle (Git). |
| `ENV` | `dev` | `dev` enables the dev-auth seam; never use `dev` in production. |
| `LOG_LEVEL` | `INFO` | `DEBUG`/`INFO`/`WARNING`/`ERROR`. |

## LLM gateway

| Variable | Default | Purpose |
| --- | --- | --- |
| `LITELLM_BASE_URL` | `http://localhost:4001` | LiteLLM proxy the app calls. |
| `LITELLM_API_KEY` | `sk-local` | Key for the proxy. |
| `LITELLM_MASTER_KEY` | `sk-local` | Proxy master key (rotate per env). |
| `WIKI_MODEL` | `wiki-default` | Compile model alias (see `litellm_config.yaml`). |
| `WIKI_VISION_MODEL` | `wiki-vision` | Vision alias for PDF/image transcription. |
| `LLM_GATEWAY_BASE_URL` | `https://api.openai.com/v1` | Your OpenAI-compatible backend. |
| `LLM_GATEWAY_KEY` | — | Backend API key. |
| `LLM_NUM_RETRIES` / `LLM_TIMEOUT_SECONDS` | `2` / `60` | Client resilience. |

`deploy/litellm/litellm_config.yaml` maps logical aliases (`wiki-default`,
`wiki-vision`, `wiki-embed`, `wiki-anthropic`) to backing models behind your
gateway. Swap a backing model there — never hardcode provider endpoints in app code.

## Embeddings

| Variable | Default | Purpose |
| --- | --- | --- |
| `EMBEDDINGS_ENABLED` | `true` | Set `false` to skip vectors (search falls back to keyword + recency). |
| `EMBED_TIMEOUT_SECONDS` | `20` | Fail-fast budget for a single embed call. |

## Identity / auth

| Variable | Default | Purpose |
| --- | --- | --- |
| `JWT_ENABLED` | `false` | Enable JWT auth. **Off = dev seam only.** |
| `JWT_TRUSTED_ISSUERS` | — | JSON array of `{issuer, jwks_url, audience?, identity_claim?}`. |
| `JWT_IDENTITY_CLAIM` | `sub` | Claim used as `Principal.user_id`. |
| `JWT_DEV_SECRET` | — | HS256 secret for local smoke; honored only when `ENV=dev`. |
| `VITE_AUTH_MODE` | `dev` | `dev` (no login) or `password` (native email+password). |
| `default_org_slug` | `default` | The single-tenant default org (code default in `config.py`). |
| `registration_allowed_domain` | `example.com` | Domain gate for native registration. |

## Ingest limits

| Variable | Default | Purpose |
| --- | --- | --- |
| `MAX_PDF_PAGES` | `50` | Reject PDFs above this page count at upload. |
| `personal_ingest_daily_cap` | `20` | Personal-space ingests/day/user. |
