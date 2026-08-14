# apps/api/Dockerfile
#
# Installs from the committed uv.lock via `uv sync` so the image is
# bit-for-bit reproducible. The api is a uv workspace member.
#
# Build context: repo root (docker-compose sets context: .).

FROM python:3.14-slim

WORKDIR /app

# Install system dependencies required by the psycopg binary wheel.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /bin/

# Copy the workspace manifests + lock, then the package sources.
COPY pyproject.toml uv.lock /app/
COPY apps/api /app/apps/api

# Install the api package from the lockfile, pinned, no dev deps.
RUN uv sync --frozen --no-dev --package k7e-api

EXPOSE 8000

# Run Alembic migrations then start uvicorn.
# alembic must be run from the directory containing alembic.ini so it can
# locate the migrations folder via script_location = alembic.
CMD ["sh", "-c", "cd /app/apps/api && uv run alembic upgrade head && uv run uvicorn k7e_api.main:app --host 0.0.0.0 --port 8000"]
