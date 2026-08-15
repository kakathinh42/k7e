# Security hardening (production checklist)

The `.env.example` defaults and the `docker compose` stack are for **local
development only**. Before any real deployment, work through this checklist.

## Auth

- [ ] `JWT_ENABLED=true` — never run with the dev auth seam in production.
- [ ] Configure `JWT_TRUSTED_ISSUERS` with your real IdP (`issuer`, `jwks_url`,
      `audience`, `identity_claim`). Verify each issuer, not just `sub`.
- [ ] `VITE_AUTH_MODE=password` (or your SSO flow) — rebuild the web image.
- [ ] Restrict `registration_allowed_domain` to your organization's domain.
- [ ] Issue Personal Access Tokens per consumer; rotate and revoke them.

## Secrets

- [ ] Rotate **every** default: Postgres password, `LITELLM_MASTER_KEY`,
      `JWT_DEV_SECRET`, `LLM_GATEWAY_KEY`. Never keep `sk-local` / `wiki:wiki`.
- [ ] Load secrets from your secret manager, not a committed `.env`.
- [ ] `LLM_GATEWAY_KEY` and DB creds must never appear in source, tests, logs,
      or fixtures.

## Network

- [ ] Do **not** publish service ports (LiteLLM `4001`, MCP `9100`, Postgres
      `5435`) to untrusted networks. Keep them on a private Docker network.
- [ ] Terminate TLS at your ingress; the app listens on plain HTTP.
- [ ] Restrict the MCP server to trusted upstreams (it relays identity headers,
      it does not verify them).

## Data handling

- [ ] Source content is sent to your configured LLM gateway during ingestion.
      Confirm your provider's retention and training-use policy is acceptable.
- [ ] Decide a retention policy for raw documents, compiled pages, embeddings,
      and logs (they may contain personal/confidential information).
- [ ] Back up the OKF Git bundle (the canonical store) and Postgres regularly.

## Operational gaps (pre-1.0)

k7e is pre-1.0 and does not yet ship: rate limiting, automated alerts, a
defined deployment target, or a load-tested configuration. See
[`ROADMAP.md`](../../ROADMAP.md). Treat this as pilot-grade, not production-grade.
