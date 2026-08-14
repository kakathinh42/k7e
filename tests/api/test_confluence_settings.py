"""M5: Confluence connector credentials come from settings/.env (blank default)."""

from __future__ import annotations

from k7e_api.config import Settings


def test_confluence_settings_default_blank(monkeypatch):
    # pydantic-settings reads OS env by field name, so an ambient
    # CONFLUENCE_API_TOKEN / CONFLUENCE_USER_EMAIL (e.g. a dev's Confluence CLI)
    # would otherwise leak into the default. Clear them to assert the true default.
    monkeypatch.delenv("CONFLUENCE_API_TOKEN", raising=False)
    monkeypatch.delenv("CONFLUENCE_USER_EMAIL", raising=False)
    s = Settings()
    assert s.confluence_api_token == ""
    assert s.confluence_user_email == ""


def test_confluence_settings_from_kwargs():
    s = Settings(confluence_api_token="tok", confluence_user_email="a@b.co")
    assert s.confluence_api_token == "tok"
    assert s.confluence_user_email == "a@b.co"
