# Connectors

A connector implements the `Connector` protocol (`base.py`): a `name` and a
`fetch() -> Iterable[FetchedDocument]`. `ingest_service.run_connector` pulls every
document and ingests it **idempotently** — unchanged content (same
`(source_system, source_external_id)` + `sha256`) is skipped; changed content
flows through the pipeline as a reviewed update.

## Implemented
- `FilesystemConnector` — a directory of files as Tier-A documents (no credentials).

## Adding a credentialed connector (Confluence / Jira / Zoom / Slack)
1. Add `connectors/<system>.py` implementing `Connector`.
2. Read API credentials from settings/env (never hardcode; follow the
   `LLM_GATEWAY_KEY` pattern — secrets live in `.env`).
3. Map each external page/message to a `FetchedDocument`:
   - `source_system` = e.g. `"confluence"`, `source_external_id` = the stable
     external id (page id, message id), `source_tier` = `"A"` for pages,
     `"B"` for conversations.
4. Return bytes + content type. The ingest service handles hashing, idempotency,
   storage, and starting the workflow.

## Scheduling (auto-ingest)
`run_connector` is the unit a scheduler invokes. In production, wrap it in a
**Temporal Schedule** (preferred — durable, observable) or a cron job that calls
an admin endpoint. Each run is idempotent, so over-frequent schedules are safe.
This repo ships the building block; wiring a live schedule requires a running
Temporal cluster and connector credentials.
