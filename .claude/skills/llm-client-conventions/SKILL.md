---
name: llm-client-conventions
description: Conventions for making LLM calls in the k7e codebase. Use as background knowledge whenever writing or modifying code that calls a model, parses model output, or selects a model in apps/api or apps/worker.
user-invocable: false
---

# LLM client conventions

All model traffic in this repo flows through **LiteLLM**, which proxies to the **OpenAI-compatible LLM gateway** (OpenAI-compatible). Follow these rules when touching any LLM code.

## Use the shared client
- Call models through `LiteLLMClient` in `apps/api/src/k7e_api/llm_client.py`. The entry point is `complete_json(system=..., user=..., schema_name=...) -> dict`.
- The `LLMClient` Protocol defines the contract; `StubLLMClient` is the deterministic test double. New call sites should depend on the `LLMClient` protocol, not a concrete class, so tests can inject the stub.
- Do **not** instantiate provider SDKs (`openai`, `anthropic`) directly anywhere. Only `litellm` is called, and only from `llm_client.py`.
- The worker depends on the API package (`k7e-api`), so reuse `k7e_api.llm_client` from `apps/worker` rather than duplicating client setup.

## Configuration (never hardcode)
- Settings come from `get_settings()` in `apps/api/src/k7e_api/config.py`:
  - `litellm_base_url` (`LITELLM_BASE_URL`) — `http://litellm:4000` inside Docker, `http://localhost:4001` from the host.
  - `litellm_api_key` (`LITELLM_API_KEY`).
  - `wiki_model` (`WIKI_MODEL`, default `wiki-default`).
- Model names are **logical LiteLLM aliases**, not raw provider ids. `LiteLLMClient` prefixes a bare alias with `openai/` (so `wiki-default` → `openai/wiki-default`) to route it through the gateway. Add or change models in `deploy/litellm/litellm_config.yaml`, then reference the alias.
- Never put a provider endpoint (e.g. `api.openai.com`, the LLM gateway URL) in application code — endpoints live in `litellm_config.yaml` and env vars only.

## Output handling & secrets
- Prompts that need structured output use `response_format={"type": "json_object"}` and must tolerate parse failure by raising `LLMOutputError` (see `complete_json`). Never silently swallow malformed model output.
- `LLM_GATEWAY_KEY` and other secrets live only in `.env` / the gateway config — never in source, tests, fixtures, or logs.

## Adding a model or provider
1. Add the model entry to `deploy/litellm/litellm_config.yaml`.
2. Reference it by its LiteLLM alias in code/config — never by a raw provider id.
3. Keep the OpenAI-compatible call shape so it continues to route through the gateway.
