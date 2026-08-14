# apps/mcp/Dockerfile
#
# The k7e MCP server (streamable-http). It is a thin HTTP client over the
# wiki API, so it needs no DB driver — just `mcp` + `httpx`.
#
# Installs from the committed uv.lock via `uv sync` (reproducible).
# Build context: repo root (docker-compose sets context: .).

FROM python:3.12-slim

WORKDIR /app

# Install uv.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /bin/

# Copy the workspace manifests + lock, then the package source.
COPY pyproject.toml uv.lock /app/
COPY apps/mcp /app/apps/mcp

# Install the mcp package from the lockfile, pinned, no dev deps.
RUN uv sync --frozen --no-dev --package k7e-mcp

# Streamable-http MCP endpoint (served at /mcp).
EXPOSE 9100

# Serve over streamable-http. K7E_API_BASE / K7E_MCP_HOST / K7E_MCP_PORT come
# from the environment (set in docker-compose).
CMD ["uv", "run", "k7e-mcp-http"]
