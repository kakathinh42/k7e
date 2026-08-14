# Quickstart: offline demo (no API key)

The offline demo proves the **entire pipeline** end to end without any external
LLM gateway. It uses deterministic stub LLM and embedding clients and a small
synthetic corpus, so a reviewer or new contributor can see k7e work in a
few minutes with zero credentials.

## What it does

1. Boots the stack (Postgres+pgvector, Temporal, api, worker) with the LLM and
   embedding clients swapped for deterministic stubs.
2. Ingests a synthetic corpus across two orgs/spaces and two team memberships.
3. Runs the Temporal ingestion workflow: redact → compile (stub LLM) → mirror
   (stub embeddings) → link graph.
4. Asserts the core loop:
   - the upload was accepted and a Temporal workflow started,
   - the stub-compiled page was mirrored into Postgres,
   - the page is retrievable via the search API (keyword + recency),
   - the full compiled page (with its source provenance) is fetchable by slug.

Permission-aware retrieval (one user sees a page another cannot) is exercised
by the RBAC test suite (`tests/api/test_retrieval_scoping.py`,
`test_effective_principal_with_teams.py`) rather than this smoke demo, since
the offline demo uses the single dev-auth identity.

## Run it

```bash
cp .env.example .env
make demo
```

`make demo` is `docker compose --profile demo up --build -d && ./scripts/demo.sh`.
The script exits non-zero if any assertion fails.

> The demo profile does **not** start the LiteLLM gateway or the web UI — it
> exercises the API + worker + MCP surface over HTTP. Point a browser at the web
> UI via the full-stack quickstart instead.

## When to use the full stack instead

Use [quickstart-gateway.md](quickstart-gateway.md) when you want real LLM
compilation quality, the web UI, or the MCP server with a real model.
