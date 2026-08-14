"""M6: ClientApp registry model."""

from __future__ import annotations

import uuid

from k7e_api.models import ClientApp


def test_client_app_round_trip(sqlite_factory):
    org = uuid.uuid4()
    with sqlite_factory() as s:
        s.add(ClientApp(org_id=org, slug="chat-agent", name="Chat Agent", api_key_hash="a" * 64))
        s.commit()
    with sqlite_factory() as s:
        app = s.query(ClientApp).filter_by(slug="chat-agent").one()
        assert app.org_id == org
        assert app.api_key_hash == "a" * 64


def test_client_app_unique_slug_per_org(sqlite_factory):
    import pytest
    from sqlalchemy.exc import IntegrityError

    org = uuid.uuid4()
    with sqlite_factory() as s:
        s.add(ClientApp(org_id=org, slug="dup", name="A", api_key_hash="1" * 64))
        s.add(ClientApp(org_id=org, slug="dup", name="B", api_key_hash="2" * 64))
        with pytest.raises(IntegrityError):
            s.commit()
