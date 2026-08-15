"""FastAPI application entry point for k7e API."""

from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse

from k7e_api.errors import install_error_handlers
from k7e_api.health import readiness
from k7e_api.logging_setup import configure_logging
from k7e_api.metrics import metrics_response
from k7e_api.middleware import PrometheusMiddleware
from k7e_api.routers import (
    apps,
    auth,
    connectors,
    facets,
    graph,
    ingest,
    items,
    pat,
    search,
    spaces,
    teams,
)

configure_logging()

app = FastAPI(title="k7e API")
app.add_middleware(PrometheusMiddleware)
install_error_handlers(app)

# Mount routers
app.include_router(apps.router, prefix="/apps", tags=["apps"])
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(pat.router, prefix="/pat", tags=["pat"])
app.include_router(connectors.router, prefix="/connectors", tags=["connectors"])
app.include_router(ingest.router, prefix="/ingest", tags=["ingest"])
app.include_router(items.router, prefix="/items", tags=["items"])
app.include_router(search.router, prefix="/search", tags=["search"])
app.include_router(spaces.router, prefix="/spaces", tags=["spaces"])
app.include_router(graph.router, prefix="/graph", tags=["graph"])
app.include_router(teams.router, prefix="/teams", tags=["teams"])
app.include_router(facets.router, prefix="/facets", tags=["facets"])


@app.get("/healthz")
def healthz() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> JSONResponse:
    """Readiness probe: 200 when all dependencies are reachable, else 503."""
    ready, checks = await readiness()
    body = {"status": "ready" if ready else "not_ready", "checks": checks}
    return JSONResponse(body, status_code=200 if ready else 503)


@app.get("/metrics")
def metrics() -> Response:
    """Prometheus metrics endpoint."""
    return metrics_response()
