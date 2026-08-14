"""Migration 0025: ClientApp delegation columns default off."""

from __future__ import annotations

from k7e_api.models import ClientApp, Organization


def test_clientapp_delegation_defaults(sqlite_factory):
    with sqlite_factory() as session:
        org = Organization(slug="o", name="O")
        session.add(org)
        session.flush()
        app = ClientApp(org_id=org.id, slug="chat-agent", name="Chat Agent", api_key_hash="h")
        session.add(app)
        session.commit()
        assert app.can_delegate_identity is False
        assert app.allowed_identity_domain is None


def test_clientapp_delegation_settable(sqlite_factory):
    with sqlite_factory() as session:
        org = Organization(slug="o2", name="O2")
        session.add(org)
        session.flush()
        app = ClientApp(
            org_id=org.id,
            slug="ca",
            name="CA",
            api_key_hash="h2",
            can_delegate_identity=True,
            allowed_identity_domain="example.com",
        )
        session.add(app)
        session.commit()
        assert app.can_delegate_identity is True
        assert app.allowed_identity_domain == "example.com"
