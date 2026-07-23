#!/bin/bash
# PreToolUse(Edit|Write): ask before touching a site-config YAML.
# autogis/config/*.yaml are site-specific and several carry DRAFT status
# (screening levels, H281 profile). Guard against an accidental overwrite by
# emitting an "ask" decision; the user confirms or declines in the UI.
set -euo pipefail

payload=$(cat)
fp=$(printf '%s' "$payload" \
  | python -c "import sys,json;print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))" \
  2>/dev/null || true)

# Normalize backslashes so Windows-style paths still match.
norm=$(printf '%s' "$fp" | tr '\\' '/')

case "$norm" in
  */autogis/config/_templates/*|*/autogis/config/recipes/*)
    # Additive, generic content (init-site skeleton templates, example workflow
    # recipes) -- NOT the site-specific / DRAFT configs this guard protects.
    exit 0
    ;;
  */autogis/config/*.yaml|*/autogis/config/*.yml)
    python -c "import json;print(json.dumps({'hookSpecificOutput':{'hookEventName':'PreToolUse','permissionDecision':'ask','permissionDecisionReason':'Editing a site-config YAML under autogis/config/ (site-specific; some are DRAFT). Confirm this change is intentional.'}}))"
    ;;
  *)
    exit 0
    ;;
esac
