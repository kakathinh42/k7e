"""Centralized exception handling: a consistent envelope for unhandled errors."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from k7e_api.logging_setup import get_logger

logger = get_logger(__name__)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.warning(
            "unhandled_exception",
            path=request.url.path,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "Internal server error"}},
        )
