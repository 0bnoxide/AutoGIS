#!/bin/bash
# SessionStart hook for Claude Code — runs in both local and remote sessions.
# Always: refresh the codebase-memory knowledge graph (logs outcome to
# ~/.cache/codebase-memory-mcp/last-index.log — silent no-op was the old bug).
# Always: install project deps.
set -euo pipefail

# --- Refresh codebase-memory knowledge graph ------------------------------
# Resolve the binary from PATH (the npm-global install) instead of a hardcoded
# path. The old hardcoded path silently rotted to a no-op when the install
# moved (.../Local/Programs -> npm global), so the index went chronically stale
# with zero signal — all output was sent to /dev/null. Now: index synchronously
# and ALWAYS log the outcome (status + node/edge counts) so a failed or stale
# index is a one-`cat last-index.log` diagnosis next session. See the 2026-06-30
# deviation log in docs/codebase-memory-mcp.md. repo_path is the canonical
# checkout (not $CLAUDE_PROJECT_DIR) so worktree sessions refresh the one
# registered project; forward slashes required by the JSON arg.
CBM="$(command -v codebase-memory-mcp || true)"
CBM_LOG="$HOME/.cache/codebase-memory-mcp/last-index.log"
mkdir -p "$(dirname "$CBM_LOG")"
if [ -n "$CBM" ]; then
  if "$CBM" cli index_repository '{"repo_path":"C:/Users/ichbi/AutoGIS","mode":"full"}' >/dev/null 2>&1; then
    echo "$(date -Iseconds) ok $("$CBM" cli index_status '{"project":"C-Users-ichbi-AutoGIS"}' 2>/dev/null)" >> "$CBM_LOG"
  else
    rc=$?
    echo "$(date -Iseconds) FAILED index_repository rc=$rc" >> "$CBM_LOG"
  fi
else
  echo "$(date -Iseconds) FAILED codebase-memory-mcp not found on PATH" >> "$CBM_LOG"
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# --- Start every session from a current pull (so sessions + the subagents and
# worktrees that branch from HEAD develop against up-to-date code). Only on a
# clean 'main' checkout, fast-forward only; fully guarded so a network/auth/
# non-ff failure can't abort the rest of setup under `set -e`. Never pull onto a
# feature branch or worktree. ponytail: ff-only on clean main; nothing fancier.
if [ "$(git -C "$PROJECT_DIR" branch --show-current 2>/dev/null)" = "main" ] \
   && [ -z "$(git -C "$PROJECT_DIR" status --porcelain 2>/dev/null)" ]; then
  git -C "$PROJECT_DIR" pull --ff-only >/dev/null 2>&1 || true
fi

# Keep stdout clean in synchronous mode: send all install chatter to stderr.
{
  # --- AutoGIS project deps (so the 113-test suite runs in fresh sessions) ---
  pip install --quiet pytest PyYAML click openpyxl
  pip install --quiet --no-deps -e "$PROJECT_DIR"
} 1>&2

# --- persist the session id for the coordination framework (coord_cli --session) ---
payload=$(cat)                                   # SessionStart payload on stdin
sid=$(printf '%s' "$payload" \
  | python -c "import sys,json;print(json.load(sys.stdin).get('session_id',''))" \
  2>/dev/null || true)
# Idempotent: append only if absent, so resume/compact re-fires don't
# accumulate duplicate export lines.
if [ -n "${CLAUDE_ENV_FILE:-}" ] && [ -n "$sid" ] \
   && ! grep -q '^export AUTOGIS_SESSION_ID=' "$CLAUDE_ENV_FILE" 2>/dev/null
then
  echo "export AUTOGIS_SESSION_ID=$sid" >> "$CLAUDE_ENV_FILE"
fi
