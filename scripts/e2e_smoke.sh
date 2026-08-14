#!/usr/bin/env bash
# e2e_smoke.sh — End-to-end smoke check for the k7e.
#
# USAGE:
#   docker compose up -d   # Start the full stack first
#   bash scripts/e2e_smoke.sh
#
# Requirements: bash, curl, grep
#
# Steps:
#   1. Wait for API health endpoint (/healthz) — required; fail on timeout.
#   2. Upload README.md to /ingest/upload — required; fail if workflow_id missing.
#   3. Poll /items and /review/pending for non-empty results — best-effort; warn only.
#   4. Print ingest metric from /metrics — informational only.
#   5. Print final success banner.

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_BASE="${API_BASE:-http://localhost:8001}"
HEALTH_TIMEOUT=60      # seconds to wait for API to become healthy
INGEST_TIMEOUT=60      # seconds to poll for ingestion result
POLL_INTERVAL=3        # seconds between poll attempts
UPLOAD_FILE="${UPLOAD_FILE:-README.md}"

# ---------------------------------------------------------------------------
# Colour helpers (gracefully degrade when tty is not available)
# ---------------------------------------------------------------------------
if [ -t 1 ]; then
  RED='\033[0;31m'
  YELLOW='\033[1;33m'
  GREEN='\033[0;32m'
  CYAN='\033[0;36m'
  BOLD='\033[1m'
  RESET='\033[0m'
else
  RED='' YELLOW='' GREEN='' CYAN='' BOLD='' RESET=''
fi

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
log_header() {
  printf "\n%s=== %s ===%s\n" "${BOLD}${CYAN}" "$*" "${RESET}"
}

log_info() {
  printf "  [INFO]  %s\n" "$*"
}

log_ok() {
  printf "  %s[OK]%s    %s\n" "${GREEN}" "${RESET}" "$*"
}

log_warn() {
  printf "  %s[WARN]%s  %s\n" "${YELLOW}" "${RESET}" "$*"
}

log_fail() {
  printf "  %s[FAIL]%s  %s\n" "${RED}" "${RESET}" "$*"
}

# ---------------------------------------------------------------------------
# Utility: wait_for_url <url> <timeout_seconds>
#   Polls GET <url> until it returns HTTP 2xx or timeout is reached.
#   Returns 0 on success, 1 on timeout.
# ---------------------------------------------------------------------------
wait_for_url() {
  local url="$1"
  local timeout="$2"
  local elapsed=0

  log_info "Polling ${url} (timeout: ${timeout}s) ..."
  while [ "${elapsed}" -lt "${timeout}" ]; do
    if curl -fsS --max-time 5 "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep "${POLL_INTERVAL}"
    elapsed=$(( elapsed + POLL_INTERVAL ))
    log_info "  ... waited ${elapsed}s"
  done
  return 1
}

# ---------------------------------------------------------------------------
# Utility: poll_nonempty_array <url> <timeout_seconds>
#   Polls GET <url> until the JSON response is not "[]" or timeout.
#   Returns 0 if non-empty array seen, 1 on timeout (best-effort — caller
#   decides whether to fail or warn).
# ---------------------------------------------------------------------------
poll_nonempty_array() {
  local url="$1"
  local timeout="$2"
  local elapsed=0
  local response

  log_info "Polling ${url} for non-empty JSON array (timeout: ${timeout}s) ..."
  while [ "${elapsed}" -lt "${timeout}" ]; do
    if response="$(curl -fsS --max-time 5 "${url}" 2>/dev/null)"; then
      # Non-empty array: not "[]" and not empty string
      if [ -n "${response}" ] && [ "${response}" != "[]" ]; then
        log_info "  Got non-empty response: ${response}"
        return 0
      fi
    fi
    sleep "${POLL_INTERVAL}"
    elapsed=$(( elapsed + POLL_INTERVAL ))
    log_info "  ... waited ${elapsed}s, still empty"
  done
  return 1
}

# ---------------------------------------------------------------------------
# Utility: poll_either_nonempty <url1> <url2> <timeout_seconds>
#   Polls two URLs per cycle within a single shared timeout budget.
#   Returns 0 as soon as either returns a non-empty array, 1 on timeout.
#   Sets global POLL_WINNER to the URL that first returned non-empty.
# ---------------------------------------------------------------------------
POLL_WINNER=""
poll_either_nonempty() {
  local url1="$1"
  local url2="$2"
  local timeout="$3"
  local elapsed=0
  local resp1 resp2

  log_info "Polling ${url1} AND ${url2} (combined timeout: ${timeout}s) ..."
  while [ "${elapsed}" -lt "${timeout}" ]; do
    # Check first URL
    if resp1="$(curl -fsS --max-time 5 "${url1}" 2>/dev/null)"; then
      if [ -n "${resp1}" ] && [ "${resp1}" != "[]" ]; then
        POLL_WINNER="${url1}"
        log_info "  Non-empty response at ${url1}: ${resp1}"
        return 0
      fi
    fi
    # Check second URL in the same cycle
    if resp2="$(curl -fsS --max-time 5 "${url2}" 2>/dev/null)"; then
      if [ -n "${resp2}" ] && [ "${resp2}" != "[]" ]; then
        POLL_WINNER="${url2}"
        log_info "  Non-empty response at ${url2}: ${resp2}"
        return 0
      fi
    fi
    sleep "${POLL_INTERVAL}"
    elapsed=$(( elapsed + POLL_INTERVAL ))
    log_info "  ... waited ${elapsed}s — both still empty"
  done
  return 1
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
  log_header "k7e — E2E Smoke Check"
  log_info "API_BASE  : ${API_BASE}"
  log_info "Timestamp : $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

  # ------------------------------------------------------------------
  # Step 1: Wait for API health endpoint (REQUIRED)
  # ------------------------------------------------------------------
  log_header "Step 1: API health check"

  if ! wait_for_url "${API_BASE}/healthz" "${HEALTH_TIMEOUT}"; then
    log_fail "API health endpoint did not become ready within ${HEALTH_TIMEOUT}s."
    log_fail "Ensure the stack is running:  docker compose up -d"
    exit 1
  fi

  health_resp="$(curl -fsS --max-time 10 "${API_BASE}/healthz")"
  log_ok "API is healthy: ${health_resp}"

  # ------------------------------------------------------------------
  # Step 2: Upload a file (REQUIRED)
  # ------------------------------------------------------------------
  log_header "Step 2: Ingest upload"

  if [ ! -f "${UPLOAD_FILE}" ]; then
    log_fail "Upload file not found: ${UPLOAD_FILE}"
    log_fail "Run this script from the repository root, or set UPLOAD_FILE=<path>."
    exit 1
  fi

  log_info "Uploading '${UPLOAD_FILE}' to ${API_BASE}/ingest/upload ..."
  upload_resp="$(curl -fsS --max-time 30 \
    -F "file=@${UPLOAD_FILE};type=text/markdown" \
    "${API_BASE}/ingest/upload")"

  log_info "Upload response: ${upload_resp}"

  # Assert response contains workflow_id
  if ! echo "${upload_resp}" | grep -q "workflow_id"; then
    log_fail "Upload response does not contain 'workflow_id'."
    log_fail "Response was: ${upload_resp}"
    exit 1
  fi

  log_ok "Upload accepted. Response contains workflow_id:"
  echo "${upload_resp}" | grep -o '"workflow_id"[^,}]*' || true

  # ------------------------------------------------------------------
  # Step 3: Poll for ingestion result (BEST-EFFORT — warn on timeout)
  # ------------------------------------------------------------------
  log_header "Step 3: Poll for ingestion result (best-effort)"
  log_info "Polling /items for non-empty results ..."
  log_info "Note: This step depends on a real LLM via LiteLLM; it may not complete"
  log_info "      if LiteLLM / OPENAI_API_KEY is not configured."

  ingestion_complete=false

  # The v2 OKF pipeline is autonomous — every upload compiles into published
  # pages that appear at /items (no review gate to poll).
  if poll_nonempty_array "${API_BASE}/items" "${INGEST_TIMEOUT}"; then
    log_ok "Found published items at /items — ingestion completed and published."
    ingestion_complete=true
  fi

  if [ "${ingestion_complete}" = false ]; then
    log_warn "/items returned no data within ${INGEST_TIMEOUT}s."
    log_warn "This is expected when LiteLLM is not configured with a real API key."
    log_warn "Steps 1 and 2 passed (upload accepted); ingestion pipeline depends on LLM."
  fi

  # ------------------------------------------------------------------
  # Step 4: Print ingest metric (informational)
  # ------------------------------------------------------------------
  log_header "Step 4: Ingest metric"
  log_info "Fetching Prometheus metrics from ${API_BASE}/metrics ..."
  metric_line="$(curl -fsS --max-time 10 "${API_BASE}/metrics" 2>/dev/null \
    | grep "wiki_ingest_total" || true)"

  if [ -n "${metric_line}" ]; then
    log_ok "wiki_ingest_total metric:"
    echo "${metric_line}"
  else
    log_warn "wiki_ingest_total not found in /metrics (may not have fired yet)."
  fi

  # ------------------------------------------------------------------
  # Step 5: Final result
  # ------------------------------------------------------------------
  log_header "Smoke Check Complete"
  log_ok "Required checks (Steps 1-2) passed."
  if [ "${ingestion_complete}" = true ]; then
    log_ok "Ingestion pipeline reached completion (Step 3 passed)."
  else
    log_warn "Ingestion pipeline not confirmed (Step 3 best-effort; see warnings above)."
  fi
  log_ok "E2E smoke check finished successfully."
}

main "$@"
