"""M6: X-App-Key -> authenticated ClientApp; key gen/hash round-trip."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from k7e_api.app_auth import generate_app_key, get_app, hash_app_key
from k7e_api.models import ClientApp


def test_generate_key_round_trips_to_hash():
    plaintext, key_hash = generate_app_key()
    assert plaintext.startswith("wapp_")
    assert len(key_hash) == 64
    assert hash_app_key(plaintext) == key_hash


def test_get_app_resolves_valid_key(sqlite_factory):
    plaintext, key_hash = generate_app_key()
    org = uuid.uuid4()
    with sqlite_factory() as s:
        s.add(ClientApp(org_id=org, slug="myapp", name="My App", api_key_hash=key_hash))
        s.commit()
    with sqlite_factory() as s:
        app = get_app(x_app_key=plaintext, session=s)
        assert app.slug == "myapp"
        assert app.org_id == org


def test_get_app_missing_key_401(sqlite_factory):
    with sqlite_factory() as s:
        with pytest.raises(HTTPException) as exc:
            get_app(x_app_key=None, session=s)
        assert exc.value.status_code == 401


def test_get_app_invalid_key_401(sqlite_factory):
    with sqlite_factory() as s:
        with pytest.raises(HTTPException) as exc:
            get_app(x_app_key="wapp_nope", session=s)
        assert exc.value.status_code == 401
