#!/bin/bash
# Sync the in-repo (vendored) ponytail skills from the locally installed
# ponytail plugin, so cloud/remote sessions and fresh clones — which do NOT
# inherit user-scope plugin installs — get the same ponytail skill set the
# maintainer runs locally (CLAUDE.md > Default working mode).
#
# There is no "plugin updated" event in Claude Code to trigger on, so this is
# run on demand after `/plugin` updates ponytail. The SessionStart hook runs it
# with --check to WARN on drift; it never auto-writes the repo (that would leave
# surprise uncommitted changes on read-only main). To apply an update: run this
# with no args, then commit on a feature branch.
#
#   sync-ponytail-skills.sh            copy latest plugin skills into the repo
#   sync-ponytail-skills.sh --check    report drift only, no writes (exit 1 = drift)
#
# ponytail: plain cp + diff -rq, no version pinning cleverness — take the
# highest installed version dir and mirror the ponytail* skills verbatim.
set -euo pipefail

CHECK=0
[ "${1:-}" = "--check" ] && CHECK=1

# Repo checkout that owns this script: .claude/scripts/ -> repo root is ../..
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DST="$(cd "$SCRIPT_DIR/../.." && pwd)/.claude/skills"

# Locally installed plugin cache (user-scope; absent on cloud/other machines).
CACHE_ROOT="$HOME/.claude/plugins/cache/ponytail/ponytail"
if [ ! -d "$CACHE_ROOT" ]; then
  echo "ponytail plugin not installed locally — nothing to sync." >&2
  exit 0   # cloud/CI has no plugin; the vendored files ARE the source there.
fi

# Highest installed version dir (version-sorted).
VER="$(ls -1 "$CACHE_ROOT" 2>/dev/null | sort -V | tail -1)"
SRC="$CACHE_ROOT/$VER/skills"
if [ -z "$VER" ] || [ ! -d "$SRC" ]; then
  echo "no ponytail skills found under $CACHE_ROOT/*/skills — nothing to sync." >&2
  exit 0
fi

drift=0
for skill_dir in "$SRC"/ponytail*/; do
  [ -d "$skill_dir" ] || continue
  name="$(basename "$skill_dir")"
  if [ "$CHECK" = 1 ]; then
    if ! diff -rq "$skill_dir" "$DST/$name/" >/dev/null 2>&1; then
      echo "DRIFT: vendored $name differs from plugin $VER" >&2
      drift=1
    fi
  else
    mkdir -p "$DST/$name"
    cp -R "$skill_dir." "$DST/$name/"
    echo "synced $name <- plugin $VER"
  fi
done

if [ "$CHECK" = 1 ] && [ "$drift" = 1 ]; then
  echo "run .claude/scripts/sync-ponytail-skills.sh (on a branch) to update vendored ponytail." >&2
  exit 1
fi
