#!/usr/bin/env bash
# scripts/demo.sh — offline pipeline assertion for the k7e demo stack.
#
# Boots nothing itself; run AFTER `docker compose -f docker-compose.demo.yml up -d`
# (or via `make demo`). Uploads a synthetic doc, waits for the Temporal workflow
# to compile + mirror it, then asserts the compiled page is retrievable via the
# search API. Exits non-zero on any failure.
#
# Uses the dev auth seam (JWT_ENABLED=false) — the api accepts the request as a
# fixed dev identity, so no token is needed.
set -euo pipefail

API="http://localhost:8001"
STUB_SLUG="hot-cache-pattern"   # the StubLLMClient always compiles this slug

green() { printf "\033[32m%s\033[0m\n" "$*"; }
red()   { printf "\033[31m%s\033[0m\n" "$*"; }

echo "→ waiting for api to be ready..."
for _ in $(seq 1 60); do
  if curl -sf "$API/readyz" >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -sf "$API/readyz" >/dev/null || { red "api never became ready"; exit 1; }
green "api ready"

echo "→ uploading a synthetic source document..."
TMP=$(mktemp -d)
printf "# Hot Cache Pattern\n\nA rolling recent-context summary file for agents.\n" > "$TMP/hot-cache.md"
UPLOAD=$(curl -sf -X POST "$API/ingest/upload" \
  -F "file=@$TMP/hot-cache.md" \
  -F "source_system=manual_upload")
rm -rf "$TMP"
echo "$UPLOAD" | grep -q "workflow_id" || { red "upload did not return a workflow_id: $UPLOAD"; exit 1; }
green "upload accepted: $UPLOAD"

echo "→ waiting for the compile + mirror workflow to complete..."
# The stub LLM returns instantly, so the page should be searchable within a few
# seconds. Poll search until the compiled slug appears (or timeout).
found=""
for _ in $(seq 1 45); do
  found=$(curl -sf "$API/search?q=hot+cache&limit=10" || echo "")
  if echo "$found" | grep -q "$STUB_SLUG"; then
    green "compiled page mirrored and searchable"
    break
  fi
  sleep 2
done
echo "$found" | grep -q "$STUB_SLUG" || { red "compiled page never appeared in search"; exit 1; }

echo "→ fetching the full compiled page..."
PAGE=$(curl -sf "$API/items/$STUB_SLUG" || echo "")
echo "$PAGE" | grep -qi "overview" || { red "page body missing expected section"; exit 1; }

green "=========================================="
green "DEMO PASSED — full pipeline verified:"
green "  upload → redact → compile (stub LLM)"
green "  → mirror (stub embeddings) → search"
green "=========================================="
