"""Dependency readiness checks for the /readyz endpoint.

Each check is independent and timeout-bounded so /readyz never hangs.
"""

from __future__ import annotations

import asyncio
import os

from sqlalchemy import text

from k7e_api.config import get_settings
from k7e_api.db import SessionLocal
from k7e_api.temporal_client import get_temporal_client

_TEMPORAL_CONNECT_TIMEOUT = 3.0


def check_db() -> bool:
    """Return True if the database answers a trivial query."""
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def check_temporal() -> bool:
    """Return True if a Temporal client connects within the timeout."""
    try:
        await asyncio.wait_for(get_temporal_client(), timeout=_TEMPORAL_CONNECT_TIMEOUT)
        return True
    except Exception:
        return False


def check_object_store() -> bool:
    """Return True if the object-store path exists and is writable."""
    path = get_settings().object_store_path
    try:
        os.makedirs(path, exist_ok=True)
        return os.access(path, os.W_OK)
    except Exception:
        return False


async def readiness() -> tuple[bool, dict[str, str]]:
    """Run all checks; return (overall_ready, per-check status map)."""
    db_ok = check_db()
    temporal_ok = await check_temporal()
    store_ok = check_object_store()
    checks = {
        "db": "ok" if db_ok else "error",
        "temporal": "ok" if temporal_ok else "error",
        "object_store": "ok" if store_ok else "error",
    }
    return (db_ok and temporal_ok and store_ok, checks)
