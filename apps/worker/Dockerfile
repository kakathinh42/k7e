# apps/worker/Dockerfile
#
# Installs from the committed uv.lock via `uv sync` so the image is bit-for-bit
# reproducible. The worker depends on the api package through the uv workspace
# (apps/worker/pyproject.toml [tool.uv.sources] -> workspace member), which
# replaces the old file:///${PROJECT_ROOT} path hack + manual dep duplication.
#
# Build context: repo root (docker-compose sets context: .).

FROM python:3.12-slim

WORKDIR /app

# System deps: libpq-dev for the psycopg binary wheel; git for the OKF bundle
# (the canonical store is a git repo of typed Markdown pages it commits to).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv (from the official image, no install script).
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /bin/

# Copy the workspace manifests + lock, then the package sources.
COPY pyproject.toml uv.lock /app/
COPY apps/api    /app/apps/api
COPY apps/worker /app/apps/worker
COPY apps/mcp    /app/apps/mcp

# Install the worker (and its workspace dep k7e-api) from the lockfile,
# pinned and without dev deps.
RUN uv sync --frozen --no-dev --package k7e-worker

CMD ["uv", "run", "python", "-m", "k7e_worker.main"]
