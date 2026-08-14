"""M0 hardening — env-gate the dev/reviewer default identity.

``get_principal`` must only fall back to the convenient ``dev``/``reviewer``
identity in the ``dev`` environment. In any other environment a missing gateway
identity yields an **anonymous** principal (no roles/groups) so retrieval fails
closed. The hardcoded ``"dev"`` review/write backdoor is likewise only honored
in dev.
"""

from __future__ import annotations

from k7e_api.auth import (
    GroupAuthorizationService,
    OpenAuthorizationService,
    Principal,
    _dev_backdoor,
    get_principal,
)
from k7e_api.rbac import HierarchicalRbacAuthorizationService


class _Settings:
    """Minimal settings stub exposing only the ``env`` attribute used here."""

    def __init__(self, env: str) -> None:
        self.env = env


def _patch_env(monkeypatch, env: str) -> None:
    monkeypatch.setattr("k7e_api.auth.get_settings", lambda: _Settings(env))


# --- get_principal defaults -------------------------------------------------


def test_get_principal_dev_env_keeps_dev_reviewer_default(monkeypatch):
    _patch_env(monkeypatch, "dev")
    p = get_principal(x_user_id=None, x_user_roles=None, x_user_groups=None)
    assert p.user_id == "dev"
    assert p.roles == ["reviewer"]
    assert p.groups == []


def test_get_principal_prod_env_is_anonymous(monkeypatch):
    _patch_env(monkeypatch, "production")
    p = get_principal(x_user_id=None, x_user_roles=None, x_user_groups=None)
    assert p.user_id == "anonymous"
    assert p.roles == []
    assert p.groups == []


def test_get_principal_headers_present_ignore_env(monkeypatch):
    # Explicit headers are honored verbatim regardless of env.
    _patch_env(monkeypatch, "production")
    p = get_principal(
        x_user_id="alice", x_user_roles="editor, viewer", x_user_groups="eng,platform"
    )
    assert p.user_id == "alice"
    assert p.roles == ["editor", "viewer"]
    assert p.groups == ["eng", "platform"]


# --- dev backdoor gating ----------------------------------------------------


def test_dev_backdoor_only_in_dev_env(monkeypatch):
    dev = Principal(user_id="dev", roles=[], groups=[])
    _patch_env(monkeypatch, "dev")
    assert _dev_backdoor(dev) is True
    _patch_env(monkeypatch, "production")
    assert _dev_backdoor(dev) is False


def test_services_no_dev_autopass_in_prod(monkeypatch, sqlite_factory):
    _patch_env(monkeypatch, "production")
    dev = Principal(user_id="dev", roles=[], groups=[])

    # Open service: reviewer role still None, dev backdoor gated off.
    assert OpenAuthorizationService().can_review(dev) is False
    # Group service: same.
    assert GroupAuthorizationService().can_review(dev) is False
    assert GroupAuthorizationService().can_write(dev) is False
    # RBAC service: no reviewer/editor grant for user "dev", backdoor gated off.
    rbac = HierarchicalRbacAuthorizationService(session_factory=sqlite_factory)
    assert rbac.can_review(dev) is False
    assert rbac.can_write(dev) is False


def test_services_dev_autopass_in_dev(monkeypatch, sqlite_factory):
    _patch_env(monkeypatch, "dev")
    dev = Principal(user_id="dev", roles=[], groups=[])
    assert OpenAuthorizationService().can_review(dev) is True
    assert GroupAuthorizationService().can_review(dev) is True
    assert GroupAuthorizationService().can_write(dev) is True
    rbac = HierarchicalRbacAuthorizationService(session_factory=sqlite_factory)
    assert rbac.can_review(dev) is True
    assert rbac.can_write(dev) is True
