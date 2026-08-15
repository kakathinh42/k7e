# Security Policy

## Supported versions

k7e is pre-1.0 software. Security fixes are applied to the latest `main`
and the most recent release tag only.

| Version | Supported |
| ------- | --------- |
| latest `main` | ✅ |
| latest tag (`v0.1.x`) | ✅ |
| older tags | ❌ |

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Please report privately using **GitHub Security Advisories**:

1. Go to https://github.com/kakathinh42/k7e/security/advisories/new
2. Click **Report a vulnerability**.
3. Include: a description, reproduction steps, affected versions, and impact.

We acknowledge reports within **3 business days** and aim to ship a fix or
mitigation within **30 days** for high-severity issues, coordinated with you on
disclosure timing. Please do not disclose the issue publicly until a fix is released.

## Local development defaults are NOT production-safe

The `.env.example` defaults and the `docker compose` stack are for **local
development only**:

- `JWT_ENABLED=false` and `VITE_AUTH_MODE=dev` (dev auth seam — no real login).
- Weak local DB credentials and a `sk-local` LiteLLM master key.
- LiteLLM is published on a host port.

Before any real deployment, follow [`docs/operations/security-hardening.md`](docs/operations/security-hardening.md):
enable JWT auth, rotate all secrets, restrict `registration_allowed_domain`,
terminate TLS, and avoid exposing service ports to untrusted networks.

## Data handling

k7e sends source document content to your configured LLM gateway during
ingestion. Ensure your gateway/provider's data-retention and training-use policy
is acceptable before ingesting sensitive material. See
[`docs/concepts/overview.md`](docs/concepts/overview.md) for the full data flow.
