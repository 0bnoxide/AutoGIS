#!/bin/bash
# PostToolUse(Bash): after a `git push`, surface the open PR URL for the current
# branch (or nudge to create one) so a pushed branch never goes untracked.
# Requires an authenticated `gh`; degrades silently if gh is absent.
set -euo pipefail

payload=$(cat)
cmd=$(printf '%s' "$payload" \
  | python -c "import sys,json;print(json.load(sys.stdin).get('tool_input',{}).get('command',''))" \
  2>/dev/null || true)

case "$cmd" in
  *"git push"*) ;;
  *) exit 0 ;;
esac

command -v gh >/dev/null 2>&1 || exit 0

branch=$(git -C "${CLAUDE_PROJECT_DIR:-.}" branch --show-current 2>/dev/null || true)
[ -n "$branch" ] || exit 0

url=$(gh pr list --head "$branch" --state open --json url --jq '.[0].url' 2>/dev/null || true)
if [ -n "$url" ]; then
  msg="Open PR for $branch: $url"
else
  msg="No open PR for $branch — run /ship to create one."
fi

MSG="$msg" python -c "import json,os;print(json.dumps({'hookSpecificOutput':{'hookEventName':'PostToolUse','additionalContext':os.environ['MSG']}}))"
