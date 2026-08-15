# k7e — Architecture

> The single source of truth for how **k7e** works today. Forward-looking plans live in [`ROADMAP.md`](ROADMAP.md); the design/decision trail is in `docs/superpowers/specs/` and `docs/superpowers/plans/`. A visual companion to this page is [`ARCHITECTURE.html`](ARCHITECTURE.html).

## What it is

**k7e** is an **engineering knowledge compiler**: it ingests raw company sources (internal wiki, Confluence, Jira, `chat-agent` conversations, meeting notes), compiles them with an LLM into reviewed, citation-backed Markdown wiki pages, and serves **permission-aware retrieval** to downstream consumers (`chat-agent` and any other internal service).

**Core principle:** *pay the synthesis cost once at ingest time so retrieval reads few, high-quality tokens.* Deterministic checks (redaction, mirroring, linking) bracket the single expensive LLM step; downstream apps read compact compiled pages instead of large raw documents.

It is **API-first and multi-consumer** — not a plugin for any one app. `chat-agent` is the first consumer; the retrieval surface is designed for future internal apps and agents too.

---

## Monorepo layout

Three deployable apps + a shared MCP server, orchestrated by `docker-compose.yml`:

| Path | Package | Role |
|---|---|---|
| `apps/api` | `k7e_api` | FastAPI service **and** shared library — HTTP surface, DB/Alembic, LLM + embedding clients, Temporal client. |
| `apps/worker` | `k7e_worker` | Temporal worker running the ingestion pipeline. Depends on `apps/api` as a package. |
| `apps/web` | — | React 19 + Vite + TypeScript SPA (TanStack Query, React Router). |
| `apps/mcp` | `k7e_mcp` | MCP server exposing `search_wiki` + `get_wiki_page` to `chat-agent` (stdio + streamable-http). |

`apps/worker` depends on the API via a `uv`-expanded path dependency (`k7e-api @ file://…/apps/api`); treat `k7e_api` as a shared library, don't duplicate its logic.

---

## Ingestion pipeline (the core flow)

Ingestion is a **Temporal workflow** — `IngestWorkflow` in `apps/worker/src/k7e_worker/workflows.py`, on the `wiki-ingest` task queue. The API starts it when a document is uploaded (`POST /ingest/upload` → `routers/ingest.py`). It is the **v2 "OKF" pipeline: one autonomous flow for every source — no gate, no human review, no Tier-A/B branch.**

```
load_raw_document → [extract_document_text_activity] → redact_activity → okf_ingest_activity → okf_mirror_activity
```

1. **`load_raw_document`** — fetch source text + metadata from the object store. Binary uploads (PDF/PNG/JPEG) return `text=None, needs_extraction=True` instead of decoding.
2. **`extract_document_text_activity`** (only when `needs_extraction`) — vision-transcribe the file to Markdown text (`extraction.py`): PDF pages are rasterized with pypdfium2 (~150 DPI JPEG) and each page/image goes through one `transcribe_image` call on the `wiki-vision` alias. Guardrails: 25 MiB upload cap for these types, `MAX_PDF_PAGES` (default 50) enforced at upload; the activity heartbeats per page and records a separate `wiki-vision` `IngestRun` row. Originals stay in the object store (not served/rendered).
3. **`redact_activity`** — replace PII with placeholders (deterministic), returning redacted text + detected categories. Runs on the extracted text for binary uploads.
4. **`okf_ingest_activity`** — the LLM step (retry `maximum_attempts=5`, transient-failure tolerant). Two-pass: the model writes **typed OKF pages** (`source` / `entity` / `concept`) and `[[wikilinks]]` between them, committed to the **OKF git bundle**. Phase A (lock-free LLM compose) + Phase B (locked write→index→log→commit) via `OkfBundle.lock()`.
5. **`okf_mirror_activity`** — mirror the bundle into Postgres (items, versions, embedded chunks, `[[wikilink]]` edges) for search + graph. Idempotent/incremental: unchanged pages are skipped; a page that previously failed to embed is retried.

The OKF git bundle of typed Markdown pages is the **canonical** knowledge store; Postgres is a derived index rebuilt from it.

**Space-targeted ingestion & per-space bundles.** `POST /ingest/upload` (optional `space=` form field) and `POST /ingest/conversation` (optional `team`) can target a specific Space instead of the default bundle; the target is recorded on `RawDocument.space_id`/`created_by`. All three OKF worker activities route through `_bundle_for(space_slug)` (`okf_activities.py`), which resolves to `<okf_bundles_root>/<slug>/` when a space is set, else the legacy default bundle. **Per-space bundles are the actual privacy boundary, not just plumbing**: OKF compose only ever merges knowledge *within one bundle*, so a personal or team-private page can never surface in another space's derived entity/concept pages — a structural guarantee that holds even before RBAC is applied.

`space=personal` (upload) or an absent `team` (conversation) resolves to the caller's **personal space** — a bare `Space` (`owner_user_id` set; no `Team`/`Membership`/group row) **JIT-provisioned** on first use (`personal_spaces.py`: idempotent lookup-or-create, direct `editor`+`admin` grants for the owner, retry-safe under a concurrent-first-ingest race). Personal ingest is rate-capped (`personal_ingest_daily_cap`, default 20/day) and gated by `require_verified_identity` — outside `env=dev`, only a JWT-verified principal or a delegated principal (`Principal.verified=True`, below) may target `personal`; a raw, unverified header can't self-assert into someone else's identity.

> **Note:** the v1 confidence **gate** (`gate_min_confidence`, publish/review/reject) was removed in the v2 OKF cutover. The `confidence` columns survive only as dormant plumbing. (CLAUDE.md still describes the old gate — that line is stale; this document is current.)

---

## Storage

Hybrid by design:

- **OKF git bundle** (`okf_bundle.py`, `okf_mirror.py`) — the canonical typed-Markdown knowledge artifact, with file locking for concurrent ingests.
- **Object store** (`object_store.py`, filesystem at `OBJECT_STORE_PATH`) — immutable raw source documents.
- **PostgreSQL** (SQLAlchemy 2 + Alembic) — the product-runtime mirror: `KnowledgeItem` / `KnowledgeItemVersion`, `WikiChunk` (embeddings), `WikiLink` (graph edges), `RawDocument`, `Source`, review/ingest-run tables. **pgvector** backs vector search (migration `0014`: a vector embedding column + HNSW index; exact cosine computed in SQL). Alembic head: `0014_pgvector_embeddings`.

---

## Retrieval & ranking

`HybridSearchProvider` (`search.py`) blends four signals per query and is exposed on `GET /search` (and the MCP `search_wiki` tool):

```
score =  w_keyword  · keyword_score          (lexical: fraction of query terms in title+body; CJK bigram-aware)
       + w_vector   · max_chunk_cosine        (semantic: best pgvector cosine over the page's chunks)
       + w_recency  · recency_decay           (exp(-age_days / halflife); freshness from updated_at)
       + w_importance · (degree / max_degree)  (optional graph centrality)
```

Defaults: `w_keyword=1.0`, `w_vector=1.0`, `w_recency=0.3` (halflife 30d), `w_importance=0.1`. The blended score is **not** normalized (ceiling ≈ 2.4) — compare within one result set, not as a percentage.

- **Relevance gate (pre-ranking):** a page is scored only if `keyword_score > 0` **OR** `max_chunk_cosine ≥ search_min_vector_similarity` (default `0.3`) — weak noise never reaches the ranked list.
- **Graph expansion (post-ranking):** the top hits' 1-hop neighbours are pulled in (`graph_expand_*`), scored `edge_score · parent_score · decay`, so strongly-linked pages surface even without a direct match. Neighbour loading is **permission-filtered**.
- **Graceful degradation:** if embeddings are disabled or the embed endpoint errors, the query embedding is empty → cosines are `0.0` → search falls back to keyword + recency. It never 500s on an embedding failure.

### Knowledge graph

`WikiLink.score` (0.0–1.0) weights page→page edges, exposed on `GET /graph`:

| `origin` | Created by | score |
|---|---|---|
| `explicit` | an author/LLM `[[wikilink]]` in the body | `1.0` |
| `vector` | cosine similarity between page embeddings (`top_k_neighbors`) | the cosine |

Tuning: `link_top_k=5`, `link_min_similarity=0.6`. A pair with both edge types reports as `explicit`.

---

## Permission-aware retrieval

Retrieval is filtered by the caller's permissions **before** scoring — the core guarantee. The seam is `AuthorizationService` (`auth.py`): `allowed_item_ids(principal, session) -> set[UUID] | None` + `can_review(principal)`, wired into `/items`, `/search` (incl. graph-expansion), and `/graph`.

**Today (Piece 1 — shipped):** group-based filtering. A caller's groups arrive in the `X-User-Groups` header (`Principal.groups`); a **source** page is visible if its `allowed_groups` is null/empty (public) or intersects the caller's groups; a **derived** page (entity/concept) is visible only if every source in its `provenance.source_pages` is visible (most-restrictive — compiled knowledge can't leak a restricted source). The `/graph` endpoint only returns an edge when *both* endpoints are visible.

**Implicit self-group (personal visibility).** The `allowed_groups` intersection effectively evaluates against `principal.groups ∪ {"public"}`; every human principal additionally carries an implicit `user:<id>` (`rbac.effective_groups`, the single helper every group-filtering site reuses). Personal items are stamped `allowed_groups=["user:<id>"]` at ingest, so only the owner's self-group admits them into the visible set. This closes a hole the base personal-spaces design missed: a space grant alone wouldn't have hidden personal items, because the seeded `group:public viewer@org` grant admits every org item at the resolver's derived-visibility step regardless of which space an item is in. **Deviation from the base spec:** consequently, an org admin's `RoleGrant` still gives them **lifecycle** control over a personal Space (they can delete it) but not **read** access to its content — admin authority manages, it doesn't imply visibility.

**Write auth on a JIT personal space is authorized by construction.** When `_resolve_target_space` provisions a caller's personal space, `provision_personal_space` grants that same caller `editor`+`admin` on the row in the same transaction before the write-gate (`can_write`) runs — so the check always passes for the owner without a separate cross-session grant lookup. This isn't a bypass: a personal space's slug is derived from its owner's user id and never listed/discoverable, so the only principal who can ever address it is the one the JIT provisioning just granted.

**Read-path `space` filter** (`GET /search`, `GET /items`, `?space=<slug>` incl. the `personal` alias) resolves via `resolve_space_filter`, which — unlike the ingest-side resolver — **never JIT-provisions**: an unknown or not-yet-created personal space is a 404, not an auto-create side effect of a read. RBAC's `allowed_item_ids` still runs first, so the filter can only **narrow** an already-permitted result set, never widen it — `?space=<someone-else's-personal-slug>` returns `200 []`, not a peek at their items.

> Identity arrives via gateway-populated headers (`X-User-Id` / `X-User-Roles` / `X-User-Groups`) in dev, or a verified Bearer JWT when `JWT_ENABLED=true` (M7 + web SSO, below). RBAC over an `Org → Space → Project` hierarchy is live (`rbac.py`); see `ROADMAP.md` for what remains.

### Authentication (web + consumers)

One enforcement point: every consumer — the web SPA, chat-agent, MCP — proves *who the user is* with an `Authorization: Bearer <JWT>`; `get_principal` (`auth.py`) verifies it and everything else (roles, teams, grants) is resolved from k7e's own DB. JWTs are identity-only.

- **Verification** (`jwt_auth.py`): the token's unverified `iss` selects an entry in the trusted-issuer list (`JWT_TRUSTED_ISSUERS`, JSON; the legacy single `JWT_ISSUER`/`JWT_JWKS_URL`/`JWT_AUDIENCE` triple folds in), then the token is fully verified against that issuer's JWKS. `JWT_DEV_SECRET` (HS256) works only under `ENV=dev`. `JWT_IDENTITY_CLAIM` (default `sub`, per-issuer overridable) maps claims → `Principal.user_id` — it must land in the same namespace as `Membership.user_id`.
- **Web SPA login** (`apps/web/src/auth/`): `VITE_AUTH_MODE` picks the mode — `dev` (default; the header seam, no login UI) or `password` (native email+password login; see "Web login" below). The SPA sends its session (or PAT) Bearer on every call — the web UI is just another consumer.
- **Rollout guard**: logged-in ≠ authorized. Before flipping `JWT_ENABLED` on, seed `RoleGrant` rows for real users, or every write/review will 403.

### Delegated identity (trusted subsystem)

An alternative to end-user JWTs for server-to-server callers: an allow-listed `ClientApp` (`can_delegate_identity`, optional `allowed_identity_domain`) may act **on behalf of** an end user by sending `X-App-Key` (its own M6 app credential) plus `X-On-Behalf-Of-Email`. `get_effective_principal` (`app_auth.py`) resolves the pair into a **verified** user `Principal` (`kind="user"`, `verified=True`) keyed by the normalized (lower-cased) email — `Principal.user_id` — so it lands in the same namespace `Membership.user_id` uses everywhere else. For any caller that isn't an authenticated delegation-allowed app, the on-behalf header is **ignored** and the normal `get_principal` result (JWT / header / dev) is returned unchanged — a caller can never self-assert someone else's identity just by setting a header.

- **Org-bound, fail-closed.** A delegation-allowed app may only assert identities within its own org (`app.org_id == ctx.org_id`, checked against the resolved `TenantContext`); asserting outside it is a 403, not silently ignored.
- **Optional domain guard.** `allowed_identity_domain` (e.g. `"example.com"`) further restricts which email domain the app may assert; a mismatch is a 403.
- **Wired today at one seam**: `POST /ingest/conversation` depends on `get_effective_principal` instead of `get_principal`, so a delegated conversation ingest is attributed to (and rate-capped/routed as) the real end user — including `require_verified_identity`'s personal-space gate above, since a delegated principal is `verified=True`.
- **Why not verify the upstream token instead:** chat-agent authenticates its own users via flask_sso; k7e deliberately does **not** verify that token itself — doing so would require sharing a minting secret (or a second trust root) between the two services. Delegation keeps the trust boundary at the service level (chat-agent is the trusted subsystem; k7e trusts *it*, not the raw token) instead of duplicating token verification.
- **Deferred**: a direct end-user browser login to k7e (no app in the middle) still goes through the M7 JWT/JWKS path described above — delegation only covers server-to-server, on-behalf-of calls.

**Enabling this for a caller (operational, not code):** (1) provision a `ClientApp` row for the calling service (e.g. chat-agent) via the existing M6 app-provisioning path; (2) set `can_delegate_identity=true` on it (optionally `allowed_identity_domain="example.com"` to scope it); (3) the caller sends `X-App-Key` + `X-On-Behalf-Of-Email` over TLS on the delegated endpoint(s). No k7e code change is required to turn this on for a given app.

### Permission-aware retrieval (per-user via delegated identity)

The read endpoints — `GET /search`, `GET /items`, `GET /graph`, `GET /facets` — resolve identity through `get_effective_principal_with_teams` (`app_auth.py`): it composes the delegated resolver (`get_effective_principal`, above) with `team_groups_for_user` (`teams.py`, unioning `Membership` rows into `Principal.groups`), the same team-union `get_principal_with_teams` already did for the non-delegated path. So a chat-agent call carrying `X-App-Key` + `X-On-Behalf-Of-Email` is resolved to the real end user and scoped, via the existing RBAC seam (`allowed_item_ids`/`effective_groups`), to exactly that user's personal space + their teams + org-public — never the delegating app's own identity or another user's private items.

- **Degrades to public, never 403.** A caller without a valid delegation (no `X-App-Key`, or an app that isn't `can_delegate_identity`) falls through to the ordinary anonymous/header principal, which carries no personal or team groups — so retrieval silently narrows to public items rather than failing closed with an error. This matches the read-path philosophy elsewhere in this doc (RBAC narrows, it doesn't gate with a hard error).
- **Archive stays non-delegated.** `DELETE /items/{slug}` deliberately keeps `get_principal_with_teams` (not the `_with_teams` delegated variant) — retrieval identity is intentionally not enough to authorize a destructive write; on-behalf-of only extends the read path.
- **wiki-MCP is a relay, not a trust point.** `apps/mcp/src/k7e_mcp/server.py`'s `_forward(ctx)` reads `Authorization` / `X-App-Key` / `X-On-Behalf-Of-Email` best-effort off the incoming MCP request (absent on stdio, never raises) and `client.py`'s `_headers` forwards them to the API unchanged, preferring the delegated pair over a bearer token over the fixed dev identity. wiki-MCP does not verify or mint anything itself — the API remains the sole enforcement point, exactly as it does for every other consumer.
- **External prerequisite:** chat-agent must send `X-App-Key` + `X-On-Behalf-Of-Email` on its calls to wiki-MCP for this to take effect; wiki-MCP has nothing to forward otherwise and every retrieval falls back to the fixed service identity (public-only, per above).

### Web login (native password + Personal Access Tokens)

The web UI signs users in directly, and downstream services (chat-agent's wiki-MCP) act *as* a user via a Personal Access Token — no shared minting secret, no cross-app redirect dance. (This replaced an earlier chat-agent "broker"/dev-portal "handoff" one-time-code flow.)

- **Native login.** `VITE_AUTH_MODE=password` shows an email+password form (`apps/web/src/auth/password.ts`, `LoginPage.tsx`). `POST /auth/register` (gated to `registration_allowed_domain`, default `example.com`) creates a bcrypt-hashed `User`; `POST /auth/login` verifies it (constant-time, generic 401). Both return a **self-issued HS256 session JWT** (`session_auth.mint_session`, `iss=session_issuer`), which the SPA sends as Bearer — verified by the self-issuer branch in `jwt_auth.verify_token`: when the unverified `iss` equals `settings.session_issuer`, verification routes straight to HS256 with `session_signing_secret` instead of the trusted-issuer/JWKS lookup, so a foreign token that merely *claims* that `iss` fails the signature check and never falls through to JWKS.
- **Personal Access Tokens.** A logged-in user generates `wpat_…` tokens (`POST /pat`, managed on the web Tokens page); only their sha256 hash is stored. `get_principal` verifies a `wpat_` Bearer into the owning user's `Principal` (`pat_auth`, `auth._principal_from_pat`), so a PAT flows through the same RBAC + personal-space scoping as any other verified user. chat-agent's wiki-MCP dials with `Authorization: Bearer <pat>` for per-user retrieval + save-to-wiki.
- **Config** (`apps/api/src/k7e_api/config.py`): `session_signing_secret` (HS256 key; verification fails closed without it), `session_issuer` (default `k7e-session`; reserved — no external issuer may use this name), `session_ttl_seconds` (default 8h), and `registration_allowed_domain` / `password_min_length` / `password_max_bytes`.

---

## API surface

`apps/api/src/k7e_api/main.py` mounts four routers plus health/metrics:

| Route | Purpose |
|---|---|
| `/ingest` | upload a document → starts `IngestWorkflow`; query ingest status. |
| `/items` | list / get / archive published knowledge items (permission-filtered). |
| `/search` | hybrid permission-aware search (the primary retrieval API). |
| `/graph` | the `related` knowledge graph (nodes + edges), permission-filtered. |
| `/healthz`, `/metrics` | liveness + Prometheus metrics. |

Logging is structured (`structlog`). The **MCP server** (`apps/mcp`) exposes `search_wiki` + `get_wiki_page` to `chat-agent` over a **fixed** identity (`X-User-Id: chat-agent` / `reader`) — per-user forwarding is the pending "Piece 2" (see ROADMAP).

---

## LLM & embedding access

**All** model traffic goes through `LiteLLMClient.complete_json()` / `LiteLLMEmbeddingClient.embed()` (`llm_client.py`, `embedding_client.py`) → LiteLLM proxy → OpenAI-compatible LLM gateway (OpenAI-compatible). Model names are logical LiteLLM aliases (a bare alias is prefixed `openai/`); add models in `deploy/litellm/litellm_config.yaml`, never hardcode provider endpoints.

- **Chat/compile:** `WIKI_MODEL` (default alias `wiki-default`). `StubLLMClient` is the deterministic test double (depend on the `LLMClient` protocol).
- **Embeddings:** alias `wiki-embed` → `text-embedding-3-small` (1536-dim). Stored on `WikiChunk`; powers the vector signal.

---

## Ingestion policy (what to ingest, where)

Two independent axes — don't conflate them:

- **Authority (`source_tier`, `source_tier.py`):** **A** = authoritative/page-like (internal wiki, Confluence, Jira, manual upload) → canonical pages; **B** = conversational/signal (chat-agent, Slack, Zoom, meeting notes).
- **Visibility (Space + `allowed_groups`):** org-wide `engineering` space (public, "one graph, many teams") vs team-private (`allowed_groups=[team:slug]`).

| Source | Tier | Space / visibility | Status |
|---|---|---|---|
| internal wiki | A | `engineering`, public (`allowed_groups=[]`) | ✅ Settled — ingest 100% first; only light dedupe/stub/freshness hygiene |
| Confluence | A | `engineering`; map source ACL → `allowed_groups` | 🚧 Draft — allowlist + curation re-enters |
| Jira | A | `engineering` | 🚧 Draft — Done/Resolved decision-bearing issues only |
| chat-agent / meeting / Zoom | B | team-private (`[team:slug]`) | ↪ Team Knowledge feature; explicit save, not auto-capture |

Operating principle: **grow the corpus by evidence, not ambition** — validate retrieval with an eval set as the corpus expands beyond internal wiki.

---

## Configuration cheat-sheet

All in `apps/api/src/k7e_api/config.py` (override via `.env`):

```
# retrieval ranking
search_w_keyword=1.0  search_w_vector=1.0  search_w_recency=0.3  search_w_importance=0.1
search_recency_halflife_days=30.0   search_min_vector_similarity=0.3
# link build (graph edges)
link_top_k=5   link_min_similarity=0.6
# search graph expansion
graph_expand_enabled=True  graph_expand_top_hits=5  graph_expand_per_hit=3  graph_expand_decay=0.5
# embeddings / models
embeddings_enabled=True   wiki_embed_model=wiki-embed   wiki_model=wiki-default
```

Secrets (`LLM_GATEWAY_KEY`, DB creds) live only in `.env` (gitignored; a hook blocks edits — edit `.env.example`).

---

## Running it

```bash
cp .env.example .env          # set LLM_GATEWAY_KEY for real LLM calls
docker compose up --build     # Postgres, Temporal, LiteLLM, api, worker, web, mcp
```

**Ports differ between compose and direct runs.** `docker compose` publishes *shifted* host ports → in-container:

| Service | Compose (host) | Direct / in-container |
|---|---|---|
| API | `8001` | `8000` |
| Web | `5174` | `5173` |
| LiteLLM | `4001` | `4000` |
| Temporal | `7234` | `7233` |
| Postgres | `5435` | `5432` |
| MCP | `9100` | `9100` |

Tests: `pytest` (Python, from repo root); `npm test` / `npm run build` (web, from `apps/web`).

---

## Code map

| Concern | File |
|---|---|
| Ingest workflow / activities | `apps/worker/src/k7e_worker/workflows.py`, `activities.py`, `okf_activities.py` |
| OKF bundle + mirror | `apps/api/src/k7e_api/okf_bundle.py`, `okf_mirror.py`, `okf_ingest.py`, `wikilinks.py` |
| Retrieval / ranking | `apps/api/src/k7e_api/search.py`, `graph.py` |
| Permissions | `apps/api/src/k7e_api/auth.py` |
| Models / migrations | `apps/api/src/k7e_api/models.py`, `apps/api/alembic/versions/` |
| LLM / embeddings | `apps/api/src/k7e_api/llm_client.py`, `embedding_client.py`, `deploy/litellm/litellm_config.yaml` |
| API routers | `apps/api/src/k7e_api/routers/{ingest,items,search,graph}.py` |
| MCP server | `apps/mcp/src/k7e_mcp/server.py` |
| Config | `apps/api/src/k7e_api/config.py` |

For where the platform is heading (multi-org, RBAC, team knowledge, connectors), see [`ROADMAP.md`](ROADMAP.md).
