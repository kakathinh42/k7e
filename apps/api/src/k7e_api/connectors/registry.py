"""Build a Connector (and its config defaults) from a Space's connector_config.

Non-secret config (type/base_url/space_key/defaults) lives in
``Space.connector_config``; the API token lives in settings/.env. Dispatch on
``type``; add a new connector by adding a branch here.
"""

from __future__ import annotations

from typing import Callable

import httpx

from k7e_api.config import Settings
from k7e_api.connectors.base import Connector
from k7e_api.connectors.confluence import ConfluenceConnector
from k7e_api.models import Space


def _confluence_http_get(email: str, token: str) -> Callable[[str], dict]:
    """A real authed http_get (Confluence Basic auth). Not exercised in unit tests."""
    auth = httpx.BasicAuth(email, token)

    def _get(url: str) -> dict:
        resp = httpx.get(url, auth=auth, headers={"Accept": "application/json"}, timeout=30.0)
        resp.raise_for_status()
        return resp.json()

    return _get


def build_connector(space: Space, settings: Settings) -> Connector:
    """Build the connector for ``space`` from its config. Raises on misconfig.

    ValueError = bad/missing per-space config (client error, -> 400).
    RuntimeError = missing server-side credential (-> 500).
    """
    cfg = space.connector_config or {}
    ctype = cfg.get("type")
    if ctype == "confluence":
        base_url = cfg.get("base_url")
        space_key = cfg.get("space_key")
        if not base_url or not space_key:
            raise ValueError("confluence connector_config requires base_url and space_key")
        if not settings.confluence_api_token or not settings.confluence_user_email:
            raise RuntimeError("CONFLUENCE_API_TOKEN / CONFLUENCE_USER_EMAIL not configured")
        return ConfluenceConnector(
            base_url=base_url,
            space_key=space_key,
            http_get=_confluence_http_get(
                settings.confluence_user_email, settings.confluence_api_token
            ),
        )
    raise ValueError(f"unknown or missing connector type: {ctype!r}")


def connector_defaults(space: Space) -> dict:
    """The per-space ingest defaults (allowed_groups, owner, project, visibility)."""
    return (space.connector_config or {}).get("defaults") or {}
