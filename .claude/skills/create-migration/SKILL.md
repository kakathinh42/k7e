---
name: create-migration
description: Generate and validate a new Alembic migration for the k7e Postgres schema. Use when adding or changing SQLAlchemy models in apps/api/src/k7e_api/models.py, or when the user asks to create, author, or revise a database migration.
disable-model-invocation: true
---

# Create migration

Authors a new Alembic revision for the API's Postgres schema and verifies it round-trips before it is applied.

## Context
- Models: `apps/api/src/k7e_api/models.py` (SQLAlchemy 2 declarative).
- Alembic config + revisions: `apps/api/alembic/` and `apps/api/alembic/versions/`.
- Connection comes from `DATABASE_URL` (see `.env`). Local Postgres is published on `localhost:5433` (container `postgres:5432`); inside Docker it is `postgres:5432`.
- Always run `alembic` from the `apps/api` directory so it finds `alembic.ini`.

## Steps
1. Confirm the model change already exists in `models.py`. If not, make or confirm it first.
2. Autogenerate the revision:
   ```bash
   cd apps/api && alembic revision --autogenerate -m "<short imperative summary>"
   ```
3. Open the new file in `apps/api/alembic/versions/` and review it carefully:
   - Delete any spurious drop/create operations autogenerate sometimes emits.
   - Make `upgrade()` and `downgrade()` symmetric — `downgrade()` must reverse `upgrade()`.
   - Add indexes for new foreign keys and any column used in WHERE/ORDER BY (check `search.py`, `versioning.py`, and the item routers).
   - For a new NOT NULL column on a populated table, add a `server_default` or a data-backfill step.
4. Validate the round-trip against a running database:
   ```bash
   cd apps/api && alembic upgrade head && alembic downgrade -1 && alembic upgrade head
   ```
5. Run the persistence-touching tests:
   ```bash
   pytest tests/api/test_versioning.py tests/api/test_items_and_search.py -q
   ```
6. (Recommended) Hand the new revision to the `migration-reviewer` subagent for a reversibility / data-loss / index pass.
7. Report the revision id, what it changes, and the round-trip result.

## Guardrails
- Never edit an already-applied migration — create a new one.
- Never hand-edit the `alembic_version` table.
- Keep one logical schema change per revision.
