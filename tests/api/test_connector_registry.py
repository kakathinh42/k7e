"""M5: build a Connector from a Space's connector_config."""

from __future__ import annotations

import pytest
from k7e_api.config import Settings
from k7e_api.connectors.confluence import ConfluenceConnector
from k7e_api.connectors.registry import build_connector, connector_defaults
from k7e_api.models import Space

CFG = {
    "type": "confluence",
    "base_url": "https://x.atlassian.net/wiki",
    "space_key": "RCVN",
    "defaults": {"allowed_groups": ["fintech-vn"]},
}


def _settings(**over):
    return Settings(confluence_api_token="tok", confluence_user_email="a@b.co", **over)


def test_build_confluence_connector():
    space = Space(slug="rcvn", name="RCVN", connector_config=CFG)
    conn = build_connector(space, _settings())
    assert isinstance(conn, ConfluenceConnector)
    assert conn.name == "confluence"


def test_connector_defaults_reads_defaults():
    space = Space(slug="rcvn", name="RCVN", connector_config=CFG)
    assert connector_defaults(space) == {"allowed_groups": ["fintech-vn"]}


def test_no_config_raises_valueerror():
    space = Space(slug="rcvn", name="RCVN", connector_config=None)
    with pytest.raises(ValueError):
        build_connector(space, _settings())


def test_unknown_type_raises_valueerror():
    space = Space(slug="x", name="X", connector_config={"type": "myspace"})
    with pytest.raises(ValueError):
        build_connector(space, _settings())


def test_missing_token_raises_runtimeerror():
    space = Space(slug="rcvn", name="RCVN", connector_config=CFG)
    with pytest.raises(RuntimeError):
        build_connector(space, Settings(confluence_api_token="", confluence_user_email=""))
