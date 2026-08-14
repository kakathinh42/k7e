"""require_verified_identity — the prod identity gate for personal ingest.

dev env: header identities pass (local/test convenience). Any other env: only
a JWT-verified human principal passes. The gate leans on the get_principal
invariant that, in prod with jwt_enabled, a caller without a valid Bearer
token is forced to ``anonymous`` BEFORE the header seam — so a non-anonymous
user principal outside dev necessarily came from a verified token. With
jwt_enabled off outside dev there is no verification at all → always 403.

Settings are constructed with explicit kwargs (the conftest autouse env scrub
keeps ambient JWT_*/CONFLUENCE_* out).
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from k7e_api.auth import Principal, require_verified_identity
from k7e_api.config import Settings


def _user(user_id: str, **kwargs) -> Principal:
    return Principal(user_id=user_id, roles=[], groups=[], **kwargs)


def test_dev_header_principal_passes():
    """dev env: an unverified header identity is allowed (no raise)."""
    settings = Settings(env="dev", jwt_enabled=False)
    assert require_verified_identity(_user("bob"), settings) is None


def test_dev_passes_even_anonymous():
    """dev env short-circuits before any verification logic."""
    settings = Settings(env="dev", jwt_enabled=True)
    assert require_verified_identity(_user("anonymous"), settings) is None


def test_prod_jwt_enabled_anonymous_403():
    settings = Settings(env="prod", jwt_enabled=True)
    with pytest.raises(HTTPException) as exc:
        require_verified_identity(_user("anonymous"), settings)
    assert exc.value.status_code == 403


def test_prod_jwt_enabled_verified_user_passes():
    """In prod+jwt_enabled a non-anonymous user principal can only have come
    from a verified token (get_principal forces header callers to anonymous)."""
    settings = Settings(env="prod", jwt_enabled=True)
    assert require_verified_identity(_user("alice"), settings) is None


def test_prod_jwt_disabled_header_user_403():
    """Without jwt_enabled there is no verification outside dev → always 403,
    even for a named header identity."""
    settings = Settings(env="prod", jwt_enabled=False)
    with pytest.raises(HTTPException) as exc:
        require_verified_identity(_user("bob"), settings)
    assert exc.value.status_code == 403


def test_prod_jwt_enabled_app_principal_403():
    """Personal ingest is for humans: an app service identity is rejected."""
    settings = Settings(env="prod", jwt_enabled=True)
    with pytest.raises(HTTPException) as exc:
        require_verified_identity(_user("myapp", kind="app"), settings)
    assert exc.value.status_code == 403


def test_prod_jwt_enabled_empty_user_id_403():
    settings = Settings(env="prod", jwt_enabled=True)
    with pytest.raises(HTTPException) as exc:
        require_verified_identity(_user(""), settings)
    assert exc.value.status_code == 403


def test_staging_behaves_like_prod():
    """Any non-dev env gets the strict gate (not just literal 'prod')."""
    settings = Settings(env="staging", jwt_enabled=False)
    with pytest.raises(HTTPException):
        require_verified_identity(_user("bob"), settings)


def test_delegated_principal_is_verified_in_prod():
    """A delegated principal (verified=True) passes the gate outside dev even
    when jwt is disabled — it arrived through an authenticated trusted app."""
    from types import SimpleNamespace

    from k7e_api.auth import Principal, require_verified_identity

    settings = SimpleNamespace(env="prod", jwt_enabled=False)
    p = Principal(user_id="alice@example.com", kind="user", roles=[], verified=True)
    require_verified_identity(p, settings)  # must NOT raise


def test_unverified_header_principal_still_403_in_prod():
    from types import SimpleNamespace

    import pytest
    from fastapi import HTTPException
    from k7e_api.auth import Principal, require_verified_identity

    settings = SimpleNamespace(env="prod", jwt_enabled=False)
    p = Principal(user_id="bob", kind="user", roles=[])  # verified defaults False
    with pytest.raises(HTTPException) as exc:
        require_verified_identity(p, settings)
    assert exc.value.status_code == 403
