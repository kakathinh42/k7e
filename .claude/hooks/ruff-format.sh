#!/usr/bin/env bash
# PostToolUse hook for Edit|Write|MultiEdit.
# Formats + autofixes the edited Python file with ruff. Best-effort: never
# blocks the tool (always exits 0). No-op if ruff is not installed.
command -v ruff >/dev/null 2>&1 || exit 0
input="$(cat)"
fp="$(printf '%s' "$input" | python3 -c 'import sys, json
try:
    print(json.load(sys.stdin).get("tool_input", {}).get("file_path", ""))
except Exception:
    pass' 2>/dev/null)"
case "$fp" in
  *.py)
    ruff format "$fp" >/dev/null 2>&1
    ruff check --fix "$fp" >/dev/null 2>&1
    ;;
esac
exit 0
