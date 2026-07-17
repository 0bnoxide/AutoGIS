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
#   sync-ponytail-skills.sh            mirror latest plugin skills into the repo
#   sync-ponytail-skills.sh --check    report drift only, no writes (exit 1 = drift)
#
# It is a true MIRROR of every ponytail* skill under the vendor dir: files
# deleted upstream are removed (per-skill clean recreate) and skills removed
# upstream (destination-only ponytail* dirs) are pruned — so "synced"/"clean"
# never hide an upstream deletion. The vendor dir's ponytail* dirs are treated
# as plugin-managed; other skills there are never touched.
#
# Env overrides (for tests): PONYTAIL_CACHE_ROOT, PONYTAIL_VENDOR_DIR.
# ponytail: plain rm+cp mirror + diff -rq, no version-pinning cleverness — take
# the highest installed version dir.
set -euo pipefail

CHECK=0
[ "${1:-}" = "--check" ] && CHECK=1

# Repo checkout that owns this script: .claude/scripts/ -> repo root is ../..
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DST="${PONYTAIL_VENDOR_DIR:-$(cd "$SCRIPT_DIR/../.." && pwd)/.claude/skills}"

# Locally installed plugin cache (user-scope; absent on cloud/other machines).
CACHE_ROOT="${PONYTAIL_CACHE_ROOT:-$HOME/.claude/plugins/cache/ponytail/ponytail}"
if [ ! -d "$CACHE_ROOT" ]; then
  # Silent in --check mode: absent plugin is the expected state on cloud/CI,
  # where the vendored files ARE the source. Only speak up on an explicit run.
  [ "$CHECK" = 0 ] && echo "ponytail plugin not installed locally — nothing to sync." >&2
  exit 0
fi

# Highest installed version dir (version-sorted).
VER="$(ls -1 "$CACHE_ROOT" 2>/dev/null | sort -V | tail -1)"
SRC="$CACHE_ROOT/$VER/skills"
if [ -z "$VER" ] || [ ! -d "$SRC" ]; then
  [ "$CHECK" = 0 ] && echo "no ponytail skills found under $CACHE_ROOT/*/skills — nothing to sync." >&2
  exit 0
fi

drift=0

# Pass 1: every skill the plugin ships -> mirror into the vendor dir.
for skill_dir in "$SRC"/ponytail*/; do
  [ -d "$skill_dir" ] || continue          # unmatched glob stays literal
  name="$(basename "$skill_dir")"
  if [ "$CHECK" = 1 ]; then
    # diff -r also reports vendor-only files inside the skill, so an upstream
    # file deletion shows up as drift here too.
    if ! diff -rq "$skill_dir" "$DST/$name/" >/dev/null 2>&1; then
      echo "DRIFT: vendored $name differs from plugin $VER" >&2
      drift=1
    fi
  else
    rm -rf "$DST/$name"                     # clean recreate = drop upstream-deleted files
    mkdir -p "$DST/$name"
    cp -R "$skill_dir." "$DST/$name/"
    echo "synced $name <- plugin $VER"
  fi
done

# Pass 2: ponytail* skills present in the vendor dir but no longer in the plugin
# -> prune them (a source-only loop would report success/clean and leave them).
for dst_dir in "$DST"/ponytail*/; do
  [ -d "$dst_dir" ] || continue
  name="$(basename "$dst_dir")"
  [ -d "$SRC/$name" ] && continue          # still shipped upstream
  if [ "$CHECK" = 1 ]; then
    echo "DRIFT: vendored $name not in plugin $VER (removed upstream)" >&2
    drift=1
  else
    rm -rf "$dst_dir"
    echo "removed $name (no longer in plugin $VER)"
  fi
done

if [ "$CHECK" = 1 ] && [ "$drift" = 1 ]; then
  echo "run .claude/scripts/sync-ponytail-skills.sh (on a branch) to update vendored ponytail." >&2
  exit 1
fi
