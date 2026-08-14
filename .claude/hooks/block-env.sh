#!/usr/bin/env bash
# PreToolUse guard for Edit|Write|MultiEdit.
# Blocks writes to the live .env secrets file (holds LLM_GATEWAY_KEY and
# DB credentials). Allows .env.example and any other .env.* variant.
input="$(cat)"
fp="$(printf '%s' "$input" | python3 -c 'import sys, json
try:
    print(json.load(sys.stdin).get("tool_input", {}).get("file_path", ""))
except Exception:
    pass' 2>/dev/null)"
[ -z "$fp" ] && exit 0
if [ "$(basename "$fp")" = ".env" ]; then
  echo "BLOCKED: $fp is the live secrets file (.env) — it holds LLM_GATEWAY_KEY and DB credentials and must not be edited by the agent. Edit .env.example instead, or change .env by hand." >&2
  exit 2
fi
exit 0
