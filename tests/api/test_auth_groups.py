"""get_principal parses X-User-Groups into Principal.groups."""

from __future__ import annotations

from k7e_api.auth import Principal, get_principal


def test_groups_parsed_from_header():
    p = get_principal(
        x_user_id="alice",
        x_user_roles="reader",
        x_user_groups="eng, finance ,,platform",
    )
    assert isinstance(p, Principal)
    assert p.groups == ["eng", "finance", "platform"]


def test_groups_default_empty():
    p = get_principal(x_user_id="bob", x_user_roles="reader")
    assert p.groups == []
