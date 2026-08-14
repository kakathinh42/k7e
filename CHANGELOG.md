# Changelog

All notable changes to k7e are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Provider-agnostic LLM gateway config (`LLM_GATEWAY_BASE_URL` / `LLM_GATEWAY_KEY`)
  — any OpenAI-compatible backend works.
- Apache-2.0 license, `NOTICE`, `CONTRIBUTING`, `SECURITY`, `CODE_OF_CONDUCT`,
  `SUPPORT`, issue/PR templates, and Dependabot configuration.
- `uv` workspace with a committed `uv.lock` for reproducible installs.

### Changed
- Default seeded organization slug is now `default` (was an internal name).
- Web dependency manifests pin explicit versions (no floating `latest`).
- Docker images install from the lockfile via `uv sync --frozen`.

### Removed
- Internal sample data, benchmark corpus, and internal design-plan archive
  (`docs/superpowers/`) — not part of the public release.

## [0.1.0] - YYYY-MM-DD

Initial open-source release.
