# k7e task runner. Self-documenting: `make` (or `make help`) lists targets.
.PHONY: help install test test-py test-web test-pg test-temporal lint format build demo e2e migrate clean

PYTHON ?= python
PYTEST ?= uv run pytest

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "Usage: make \033[36m<target>\033[0m\n\n"} \
	  /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

install: ## Install Python (uv sync) + web (npm ci) deps
	uv sync
	cd apps/web && npm ci

test: ## Run lint + Python (no DB/Temporal) + web tests
	$(MAKE) lint
	$(MAKE) test-py
	$(MAKE) test-web

test-py: ## Python tests, excluding DB/Temporal/bench-gated suites
	$(PYTEST) -q --ignore tests/api/test_pgvector_search.py \
	  -k "not pg and not temporal and not bench"

test-pg: ## Postgres + pgvector integration (needs WIKI_TEST_PG_DSN)
	$(PYTEST) -q tests/api/test_pgvector_search.py tests/api/test_rbac_migration.py \
	  tests/api/test_tenant_backfill_migration.py tests/api/test_classification_migration.py \
	  tests/api/test_team_migration.py tests/api/test_clientapp_delegation_migration.py

test-temporal: ## Worker/Temporal integration (needs a Temporal dev server on TEMPORAL_HOST)
	$(PYTEST) -q tests/worker

test-web: ## Web type-check, build, and unit tests
	cd apps/web && npm run build && npm test

lint: ## ruff check + format check
	uv run ruff check apps tests
	uv run ruff format --check apps tests

format: ## ruff autofix + format
	uv run ruff check --fix apps tests
	uv run ruff format apps tests

build: ## Build all Docker images (compose)
	docker compose build

demo: ## Boot the offline demo (no LLM key) and assert the full pipeline
	docker compose -f docker-compose.demo.yml up --build -d
	./scripts/demo.sh
	@echo "Teardown: docker compose -f docker-compose.demo.yml down -v"

e2e: ## End-to-end smoke against the full stack (needs LLM_GATEWAY_KEY)
	bash scripts/e2e_smoke.sh

migrate: ## Apply Alembic migrations (DATABASE_URL must be set)
	cd apps/api && uv run alembic upgrade head

clean: ## Remove build/test artifacts
	rm -rf .pytest_cache .ruff_cache .venv apps/web/node_modules apps/web/dist
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
