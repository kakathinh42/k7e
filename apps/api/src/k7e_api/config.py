import json
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://wiki:wiki@localhost:5432/wiki"
    temporal_host: str = "localhost:7233"
    litellm_base_url: str = "http://localhost:4000"
    litellm_api_key: str = "sk-local"
    object_store_path: str = ".data/objects"
    wiki_model: str = "wiki-default"
    llm_num_retries: int = 2
    llm_timeout_seconds: float = 60.0
    # Per-million-token prices used to estimate the $ cost of each ingest.
    # Defaults track Claude Sonnet 4.x list pricing; override to match the
    # gateway's actual billing.
    llm_cost_input_usd_per_mtok: float = 3.0
    llm_cost_output_usd_per_mtok: float = 15.0
    log_level: str = "INFO"
    wiki_embed_model: str = "wiki-embed"
    embed_timeout_seconds: float = 30.0
    # Vision extraction (PDF/image uploads): the alias MUST point at a
    # vision-capable backing model or extraction fails at runtime.
    wiki_vision_model: str = "wiki-vision"
    # Hard cap on PDF pages accepted for vision extraction (rejected at upload).
    max_pdf_pages: int = 50
    # Confluence connector (M5): non-secret per-space config lives in
    # Space.connector_config; the API token + user email are secrets from .env.
    confluence_api_token: str = ""
    confluence_user_email: str = ""
    # Embeddings power vector search. They are
    # best-effort: when disabled (or when the embed endpoint errors/rate-limits)
    # ingest still succeeds and search falls back to keyword-only.
    embeddings_enabled: bool = True
    # Scheduled embedding backfill (fills WikiChunk rows the mirror left with a
    # NULL embedding). Bounded per run so it never times out or over-drives the
    # gateway; EMBEDDINGS_ENABLED=false pauses it.
    embed_backfill_batch_size: int = 100
    embed_backfill_interval_seconds: int = 120
    search_w_keyword: float = 1.0
    search_w_vector: float = 1.0
    search_w_recency: float = 0.0
    search_recency_halflife_days: float = 30.0
    search_min_vector_similarity: float = 0.3
    link_top_k: int = 5
    link_min_similarity: float = 0.6
    search_w_importance: float = 0.0
    graph_expand_enabled: bool = True
    graph_expand_top_hits: int = 5
    graph_expand_per_hit: int = 3
    graph_expand_decay: float = 0.5
    # v2 OKF: the git bundle of typed Markdown pages (the canonical store).
    okf_bundle_path: str = ".data/okf-bundle"
    # Per-space OKF bundles root: parent directory that contains one sub-directory
    # per Space slug.  E.g. ".data/okf-bundles/engineering/" holds the engineering
    # space bundle.  Task 4 uses this when mirroring space-scoped pages.
    okf_bundles_root: str = ".data/okf-bundles"
    # Multi-org tenancy: the default Organization slug resolved for single-tenant
    # mode. All call sites go through get_tenant_context() and never need to change.
    default_org_slug: str = "default"
    # Native email+password registration: only emails at this domain may
    # register; minimum password length. Empty domain disables the gate.
    registration_allowed_domain: str = "example.com"
    password_min_length: int = 8
    # bcrypt raises over 72 bytes; reject overlong passwords with a clean 400.
    password_max_bytes: int = 72
    # Personal-space ingest: max docs/day/user (uploads + conversations). 429 beyond.
    personal_ingest_daily_cap: int = 20
    env: str = "dev"
    # Authorization backend. ``"rbac"`` (default, M2) routes through the
    # hierarchical RBAC service (role grants + downward scope inheritance);
    # ``"groups"`` is the legacy Piece-1 group-enforced mode; ``"open"`` is a
    # fully-open local/dev instance. Selection in ``get_authz``: ``"rbac"``
    # wins outright; otherwise ``auth_enforce_groups`` (below) acts as a legacy
    # back-compat switch — when True it selects the group service even under
    # ``"open"``, so old deployments that set ``AUTH_ENFORCE_GROUPS=false`` to
    # reach open mode keep working, and ``auth_mode="open"`` yields Open only
    # when ``auth_enforce_groups`` is False.
    auth_mode: str = "rbac"
    # Legacy back-compat: when True (default) and ``auth_mode`` is not ``"rbac"``,
    # the group service is selected (group-filtered retrieval). Set False with
    # ``auth_mode="open"`` for a fully-open local/dev instance. Ignored under
    # ``"rbac"``.
    auth_enforce_groups: bool = True

    # M7 — JWT identity verification. Off by default = today's X-User-* seam.
    # When on: a verified Bearer JWT resolves identity (roles/teams stay
    # DB-resolved). jwt_dev_secret enables an HS256 shared-secret mode so
    # tests/compose need no live IdP; otherwise RS256 is verified via JWKS.
    jwt_enabled: bool = False
    jwt_jwks_url: str = ""
    jwt_issuer: str = ""
    jwt_audience: str = ""
    jwt_leeway_seconds: int = 60
    jwt_dev_secret: str = ""
    # Web SSO: JSON array of trusted issuer configs, each
    # {"issuer": ..., "jwks_url": ..., "audience": "", "algorithms": ["RS256"],
    #  "identity_claim": ""} — issuer + jwks_url required. Kept as a raw JSON
    # string (not a typed list field) because pydantic-settings JSON-decodes
    # complex fields straight from the env, so a blank JWT_TRUSTED_ISSUERS=
    # line in .env would crash startup; the validator below fail-fasts on
    # malformed values instead. The legacy jwt_issuer/jwt_jwks_url/jwt_audience
    # triple folds into this list at verification time (jwt_auth._issuer_configs).
    jwt_trusted_issuers: str = ""
    # Claim used as Principal.user_id for verified tokens. Namespace hedge:
    # must yield values in the same namespace as Membership.user_id /
    # RoleGrant.principal_id (e.g. switch to "email" if issuer subs are opaque).
    # A per-issuer identity_claim entry overrides this global default.
    jwt_identity_claim: str = "sub"

    # Self-issued web session (broker login). k7e signs AND verifies these
    # with session_signing_secret — sole minter+verifier, so HS256 is safe here.
    session_signing_secret: str = ""
    # RESERVED issuer name: verify_token's self-issued branch shadows any
    # JWT_TRUSTED_ISSUERS entry with this same iss (routing it to HS256
    # self-verification), so don't reuse a real IdP's iss here.
    session_issuer: str = "k7e-session"
    session_ttl_seconds: int = 28800  # 8h

    @field_validator("jwt_trusted_issuers")
    @classmethod
    def _validate_jwt_trusted_issuers(cls, v: str) -> str:
        if not v.strip():
            return v
        try:
            parsed = json.loads(v)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JWT_TRUSTED_ISSUERS is not valid JSON: {exc}") from exc
        if not isinstance(parsed, list):
            raise ValueError("JWT_TRUSTED_ISSUERS must be a JSON array")
        for i, entry in enumerate(parsed):
            if not isinstance(entry, dict):
                raise ValueError(f"JWT_TRUSTED_ISSUERS[{i}] must be a JSON object")
            if not entry.get("issuer") or not entry.get("jwks_url"):
                raise ValueError(
                    f"JWT_TRUSTED_ISSUERS[{i}] requires non-empty 'issuer' and 'jwks_url'"
                )
        return v

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
