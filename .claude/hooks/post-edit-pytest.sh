#!/bin/bash
# PostToolUse(Edit|Write): run the arcpy-free test suite after a Python edit.
# Reads the hook payload from stdin. Only fires for *.py changes; stays silent
# when tests pass so passing sessions are low-noise — failures are surfaced back
# to Claude via additionalContext so it can react without the user relaying.
set -euo pipefail

payload=$(cat)
fp=$(printf '%s' "$payload" \
  | python -c "import sys,json;print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))" \
  2>/dev/null || true)

case "$fp" in
  *.py) ;;
  *) exit 0 ;;
esac

cwd=$(printf '%s' "$payload" \
  | python -c "import sys,json;print(json.load(sys.stdin).get('cwd',''))" \
  2>/dev/null || true)
cd "${cwd:-${CLAUDE_PROJECT_DIR:-.}}" || exit 0   # stale/removed cwd: skip, don't abort
out=$(python -m pytest -q --tb=short 2>&1 || true)

# Surface only on failure/error (pytest summary: "1 failed, 86 passed").
if printf '%s' "$out" | grep -qiE '(failed|error)'; then
  tail=$(printf '%s' "$out" | tail -n 25)
  MSG="pytest reported failures after editing $fp:"$'\n'"$tail" \
    python -c "import json,os;print(json.dumps({'hookSpecificOutput':{'hookEventName':'PostToolUse','additionalContext':os.environ['MSG']}}))"
fi
