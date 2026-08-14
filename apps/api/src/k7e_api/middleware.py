"""ASGI middleware that records per-request Prometheus metrics."""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from k7e_api.metrics import HTTP_REQUEST_DURATION_SECONDS, HTTP_REQUESTS_TOTAL


class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            elapsed = time.perf_counter() - start
            route = request.scope.get("route")
            endpoint = getattr(route, "path", request.url.path)
            HTTP_REQUESTS_TOTAL.labels(request.method, endpoint, str(status_code)).inc()
            HTTP_REQUEST_DURATION_SECONDS.labels(request.method, endpoint).observe(elapsed)
