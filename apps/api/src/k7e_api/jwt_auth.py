"""M7 / web SSO: verify an ``Authorization: Bearer <JWT>`` in the auth seam.

Two modes: ``settings.jwt_dev_secret`` set **and** ``env == "dev"`` → HS256
shared-secret (tests/compose, no live IdP; ignored with a one-time warning in
any other env); else RS256 against a **trusted-issuer list** — the token's
unverified ``iss`` selects an issuer config (selection only, never trusted),
then the token is fully verified against that issuer's JWKS. The list comes
from ``settings.jwt_trusted_issuers`` (JSON); the legacy single-issuer
``jwt_issuer``/``jwt_jwks_url``/``jwt_audience`` triple folds in for
back-compat (with an empty ``jwt_issuer`` acting as the pre-list wildcard).

Identity only — returns the token's claims; roles/teams stay DB-resolved.
``identity_from_claims`` maps verified claims to ``Principal.user_id`` via the
per-issuer ``identity_claim`` or the global ``jwt_identity_claim`` setting.
Any verification failure raises :class:`JwtError` (the auth seam maps it to 401).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm

from k7e_api.logging_setup import get_logger

logger = get_logger(__name__)

_JWKS_TTL_SECONDS = 3600.0
#: {jwks_url: (fetched_at, jwks_dict)}
_JWKS_CACHE: dict[str, tuple[float, dict]] = {}

#: One-time warning latch for a jwt_dev_secret set outside env=dev.
_DEV_SECRET_WARNED = False


class JwtError(Exception):
    """Token verification failed (bad signature / expired / wrong claims / no key)."""


class JwtUnavailableError(JwtError):
    """Verification could not be performed (JWKS unavailable, cold cache).

    A *retryable infra* failure (IdP/JWKS outage), distinct from a bad token —
    the auth seam maps it to **503**, not 401. Subclasses ``JwtError`` so a
    caller that only catches ``JwtError`` still fails closed.
    """


@dataclass(frozen=True)
class IssuerConfig:
    """One trusted issuer: where its keys live and what to enforce."""

    issuer: str
    jwks_url: str
    audience: str = ""
    algorithms: tuple[str, ...] = ("RS256",)
    #: Claim used as Principal.user_id; empty → settings.jwt_identity_claim.
    identity_claim: str = ""


def _issuer_configs(settings) -> tuple[dict[str, IssuerConfig], IssuerConfig | None]:
    """Resolve the trusted-issuer map plus an optional legacy wildcard entry.

    The wildcard preserves pre-list semantics: ``jwt_jwks_url`` set with an
    empty ``jwt_issuer`` verified any token against that JWKS without an
    ``iss`` check, so such a config still matches tokens whose ``iss`` is
    absent or unknown to the list.
    """
    configs: dict[str, IssuerConfig] = {}
    raw = getattr(settings, "jwt_trusted_issuers", "") or ""
    if raw.strip():
        # Settings' field_validator fail-fasts on malformed values; a parse
        # error here means a hand-rolled stub bypassed it → treat as bad config,
        # not a bad token, hence ValueError (500) rather than JwtError (401).
        for entry in json.loads(raw):
            cfg = IssuerConfig(
                issuer=entry["issuer"],
                jwks_url=entry["jwks_url"],
                audience=entry.get("audience", "") or "",
                algorithms=tuple(entry.get("algorithms") or ("RS256",)),
                identity_claim=entry.get("identity_claim", "") or "",
            )
            configs[cfg.issuer] = cfg
    legacy_jwks = getattr(settings, "jwt_jwks_url", "") or ""
    wildcard: IssuerConfig | None = None
    if legacy_jwks:
        legacy = IssuerConfig(
            issuer=getattr(settings, "jwt_issuer", "") or "",
            jwks_url=legacy_jwks,
            audience=getattr(settings, "jwt_audience", "") or "",
        )
        if legacy.issuer:
            configs.setdefault(legacy.issuer, legacy)
        else:
            wildcard = legacy
    return configs, wildcard


def _fetch_jwks(url: str) -> dict:
    """Fetch the JWKS document over HTTP. Monkeypatched in tests (no network)."""
    resp = httpx.get(url, timeout=10.0)
    resp.raise_for_status()
    return resp.json()


def _jwks(url: str, *, force: bool = False) -> dict:
    cached = _JWKS_CACHE.get(url)
    if not force and cached is not None and (time.time() - cached[0] < _JWKS_TTL_SECONDS):
        return cached[1]
    try:
        jwks = _fetch_jwks(url)
    except Exception as exc:  # noqa: BLE001
        if cached is not None:
            return cached[1]  # serve stale on fetch failure
        # cold cache → cannot verify → fail closed, but as a retryable 503 (infra),
        # not a 401 (bad token).
        raise JwtUnavailableError(f"JWKS fetch failed (cold cache): {exc}") from exc
    _JWKS_CACHE[url] = (time.time(), jwks)
    return jwks


def _key_for_kid(jwks: dict, kid: str | None):
    for entry in jwks.get("keys", []):
        if entry.get("kid") == kid:
            return RSAAlgorithm.from_jwk(entry)
    return None


def _signing_key(token: str, jwks_url: str):
    try:
        kid = jwt.get_unverified_header(token).get("kid")
    except jwt.PyJWTError as exc:
        raise JwtError(str(exc)) from exc
    key = _key_for_kid(_jwks(jwks_url), kid)
    if key is None:  # kid rotation → refetch once
        key = _key_for_kid(_jwks(jwks_url, force=True), kid)
    if key is None:
        raise JwtError(f"no JWKS key for kid {kid!r}")
    return key


def _decode_and_check(
    token: str,
    *,
    key,
    algorithms: list[str],
    issuer: str,
    audience: str,
    leeway: int,
) -> dict:
    """Shared decode + post-checks for the HS256 and RS256 paths."""
    # ``leeway`` tolerates clock skew on iat/nbf, but must NOT extend a token's
    # usable lifetime past its stated ``exp`` — so exp is checked ourselves
    # below with zero tolerance, and PyJWT's own (leeway-widened) exp check is
    # disabled here to avoid double-guessing which one fired.
    options = {
        "require": ["exp"],
        "verify_exp": False,
        "verify_iss": bool(issuer),
        "verify_aud": bool(audience),
    }
    kwargs: dict = {"leeway": leeway, "options": options}
    if issuer:
        kwargs["issuer"] = issuer
    if audience:
        kwargs["audience"] = audience
    try:
        claims = jwt.decode(token, key, algorithms=algorithms, **kwargs)
    except jwt.PyJWTError as exc:
        raise JwtError(str(exc)) from exc

    # Zero-tolerance expiry (leeway is applied to iat/nbf only, above). ``exp``
    # presence is enforced by ``require``; guard its type so a malformed-but-
    # signed claim is a clean 401, not a 500.
    try:
        expired = float(claims["exp"]) <= time.time()
    except (TypeError, ValueError) as exc:
        raise JwtError("invalid 'exp' claim") from exc
    if expired:
        raise JwtError("token is expired")
    if not claims.get("sub"):
        raise JwtError("token missing 'sub' claim")
    return claims


def verify_token(token: str, settings) -> dict:
    """Verify a Bearer token; return its claims. Raises :class:`JwtError` on failure."""
    global _DEV_SECRET_WARNED
    if getattr(settings, "jwt_dev_secret", ""):
        if getattr(settings, "env", "dev") == "dev":
            return _decode_and_check(
                token,
                key=settings.jwt_dev_secret,
                algorithms=["HS256"],
                issuer=getattr(settings, "jwt_issuer", "") or "",
                audience=getattr(settings, "jwt_audience", "") or "",
                leeway=settings.jwt_leeway_seconds,
            )
        if not _DEV_SECRET_WARNED:
            _DEV_SECRET_WARNED = True
            logger.warning(
                "jwt_dev_secret is set but env != 'dev'; ignoring the shared "
                "secret and requiring a trusted issuer (JWKS)."
            )

    configs, wildcard = _issuer_configs(settings)
    try:
        # Unverified read of ``iss`` for issuer *selection* only — never
        # trusted. The selected entry then fully verifies signature + iss:
        # a token claiming issuer A but signed by B's key fails A's signature
        # check; one signed by A claiming iss=B never routes to A's keys.
        unverified_iss = jwt.decode(token, options={"verify_signature": False}).get("iss")
    except jwt.PyJWTError as exc:
        raise JwtError(str(exc)) from exc

    self_iss = getattr(settings, "session_issuer", "")
    if self_iss and unverified_iss == self_iss:
        secret = getattr(settings, "session_signing_secret", "")
        if not secret:
            raise JwtError("self-issued session verification not configured")
        return _decode_and_check(
            token,
            key=secret,
            algorithms=["HS256"],
            issuer=self_iss,
            audience="",
            leeway=settings.jwt_leeway_seconds,
        )

    cfg = configs.get(unverified_iss) if isinstance(unverified_iss, str) else None
    if cfg is None:
        cfg = wildcard
    if cfg is None:
        raise JwtError(f"untrusted or missing issuer {unverified_iss!r}")
    return _decode_and_check(
        token,
        key=_signing_key(token, cfg.jwks_url),
        algorithms=list(cfg.algorithms),
        issuer=cfg.issuer,
        audience=cfg.audience,
        leeway=settings.jwt_leeway_seconds,
    )


def normalize_identity(value: str) -> str:
    """Case-fold email identities so one human maps to one user_id across the
    JWT and delegated seams. Opaque non-email subjects are returned unchanged."""
    v = value.strip()
    return v.lower() if "@" in v else v


def identity_from_claims(claims: dict, settings) -> str:
    """Map verified claims to ``Principal.user_id``.

    Per-issuer ``identity_claim`` wins, then the global ``jwt_identity_claim``
    setting, then ``sub``. A configured claim that is missing/empty on a
    verified token raises :class:`JwtError` (401) rather than silently falling
    back to ``sub`` — a fallback would split one human into two identities.
    """
    configs, _wildcard = _issuer_configs(settings)
    iss = claims.get("iss")
    cfg = configs.get(iss) if isinstance(iss, str) else None
    claim_name = (cfg.identity_claim if cfg else "") or (
        getattr(settings, "jwt_identity_claim", "") or "sub"
    )
    value = claims.get(claim_name)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise JwtError(f"token missing identity claim {claim_name!r}")
    return normalize_identity(str(value))
