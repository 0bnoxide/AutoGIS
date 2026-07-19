#!/bin/bash
# watch-pr-reviews.sh — robust poller for new PR reviews/comments, meant to be
# armed as a Monitor command (Claude Code). It exists because a bare `gh` poll
# with swallowed stderr fails silently forever (the "Monitor gh silent failure"
# lesson): you wait for a review that already landed, or wait through an auth
# error that never surfaces. This template bakes in the fixes:
#
#   - pins the repo (no reliance on ambient cwd)
#   - checks ALL THREE comment surfaces — they are separate GitHub endpoints:
#       pulls/{n}/reviews    review summaries (APPROVED / CHANGES_REQUESTED / …)
#       pulls/{n}/comments   inline (line-anchored) review comments
#       issues/{n}/comments  the PR conversation timeline
#   - --paginate, so a PR with >30 comments doesn't silently truncate
#   - emits POLL-FAIL <time> on any gh error instead of going quiet
#   - dedups by "TYPE id" KEY, not the display line: inline comments' path:line
#     shifts every time a commit lands on the PR (#261), and a mutable field in
#     the dedup key re-emits every already-seen item on every push
#   - the seen-file is append-only: a transiently short API response can never
#     forget ids and resurrect them later
#   - is foreground-testable with --once BEFORE you trust it in a Monitor
#
# Usage:
#   watch-pr-reviews.sh <pr>                     arm as a Monitor command
#   watch-pr-reviews.sh <pr> --once             one poll, then exit (foreground test)
#   watch-pr-reviews.sh <pr> --repo owner/name  explicit repo (else auto-detected)
#   watch-pr-reviews.sh <pr> --interval 30      seconds between polls (default 45)
#   watch-pr-reviews.sh <pr> --exclude LOGIN    skip a login (repeatable)
#   watch-pr-reviews.sh <pr> --include-self     don't skip your own comments
#   watch-pr-reviews.sh <pr> --continuous       keep emitting; don't exit on first
#   watch-pr-reviews.sh <pr> --baseline         swallow pre-existing items on the
#                                               first successful poll of THIS run
#   watch-pr-reviews.sh <pr> --seen-file PATH   pin the seen-state file (default
#                                               is under $TMPDIR, which some
#                                               harnesses vary per invocation)
#
# By default it excludes the Copilot review bot and your own login, and EXITS 0
# after the first new item so a `Monitor` fires once and stops (the common
# "wake me when the review lands" case). Arm it with persistent:true.
# For a long-lived watch, arm with --continuous --baseline so pre-existing
# items don't fire the Monitor on the first poll. If you re-run --once in a
# loop instead, pass --baseline only on the FIRST run (it swallows every poll
# it baselines). AutoGIS cold reviews use the authenticated owner's login, so
# its Monitor command must also pass --include-self and pin --repo explicitly.
# Under --once, inspect output (`NEW` / `POLL-FAIL`), not the exit status, which
# remains zero after a completed poll for compatibility.
#
#   Monitor(command: 'bash .claude/scripts/watch-pr-reviews.sh 247 --repo 0bnoxide/AutoGIS --include-self --continuous --baseline',
#           description: 'reviews on PR #247', persistent: true)
#
# ponytail: gh + awk key-set + an append-only seen-file. No state DB, no extra deps.
set -uo pipefail   # NOT -e: a transient gh failure must become POLL-FAIL, not an exit

PR=""; REPO=""; INTERVAL=45; ONCE=0; CONTINUOUS=0; INCLUDE_SELF=0
BASELINE=0; SEEN_FILE=""; FIRST=1
EXCLUDES=("copilot-pull-request-reviewer[bot]")

while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="$2"; shift 2 ;;
    --interval) INTERVAL="$2"; shift 2 ;;
    --exclude) EXCLUDES+=("$2"); shift 2 ;;
    --include-self) INCLUDE_SELF=1; shift ;;
    --once) ONCE=1; shift ;;
    --continuous) CONTINUOUS=1; shift ;;
    --baseline) BASELINE=1; shift ;;
    --seen-file)
      [ $# -ge 2 ] && [[ "$2" != --* ]] || { echo "--seen-file requires PATH" >&2; exit 2; }
      SEEN_FILE="$2"; shift 2 ;;
    -h|--help) sed -n '2,/^set -uo pipefail/ { /^set -uo pipefail/!p; }' "$0"; exit 0 ;;
    [0-9]*) PR="$1"; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
[ -n "$PR" ] || { echo "usage: watch-pr-reviews.sh <pr> [--repo o/n] [--once] ..." >&2; exit 2; }

[ -n "$REPO" ] || REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || true)"
[ -n "$REPO" ] || { echo "no repo: pass --repo owner/name (gh could not auto-detect)" >&2; exit 2; }

if [ "$INCLUDE_SELF" = 0 ]; then
  self="$(gh api user -q .login 2>/dev/null || true)"
  [ -n "$self" ] && EXCLUDES+=("$self")
fi
# JSON array of excluded logins, embedded verbatim into the gh --jq programs (a
# jq array literal of JSON strings is valid jq syntax). Built in pure bash: only
# gh's BUILT-IN --jq is available here, not a standalone `jq` binary, and GitHub
# logins are [A-Za-z0-9-]/`name[bot]` — no quotes or backslashes to escape.
_ex=""
for e in "${EXCLUDES[@]}"; do _ex="${_ex:+$_ex,}\"$e\""; done
EX="[$_ex]"

SEEN="${SEEN_FILE:-${TMPDIR:-/tmp}/watch-pr-reviews.${REPO//\//_}.${PR}.seen}"
# Sentinel first line: keeps the seen-file non-empty so awk's NR==FNR two-file
# idiom can't misread stdin as file one. Old-format files (full display lines)
# stay compatible — lookups only ever use the first two fields.
if [ ! -s "$SEEN" ] && ! printf '# watch-pr-reviews seen-keys\n' > "$SEEN" 2>/dev/null; then
  echo "POLL-FAIL $(date -u +%H:%M:%S) (cannot write seen-file: $SEEN)"
  exit 2
fi

# Emit items whose "TYPE id" key is unseen, across all three surfaces; append
# the new keys to $SEEN; return 0 if anything was emitted.
poll() {
  local ok=1 r i s cur new
  r=$(gh api --paginate "repos/$REPO/pulls/$PR/reviews" \
        --jq ".[] | select(.user.login as \$l | ($EX | index(\$l)) | not) | \"REVIEW \(.id) \(.user.login) \(.state)\"" 2>/dev/null) || ok=0
  i=$(gh api --paginate "repos/$REPO/pulls/$PR/comments" \
        --jq ".[] | select(.user.login as \$l | ($EX | index(\$l)) | not) | \"INLINE \(.id) \(.user.login) \(.path):\(.line // .original_line)\"" 2>/dev/null) || ok=0
  s=$(gh api --paginate "repos/$REPO/issues/$PR/comments" \
        --jq ".[] | select(.user.login as \$l | ($EX | index(\$l)) | not) | \"ISSUE \(.id) \(.user.login)\"" 2>/dev/null) || ok=0
  if [ "$ok" = 0 ]; then
    echo "POLL-FAIL $(date -u +%H:%M:%S) (gh error querying $REPO#$PR)"
    return 1
  fi
  cur="$(printf '%s\n%s\n%s\n' "$r" "$i" "$s" | grep -v '^$' | sort -u)"
  new="$(printf '%s\n' "$cur" | awk '
      NR==FNR { seen[$1" "$2] = 1; next }
      NF { k = $1" "$2; if (!(k in seen) && !dup[k]++) print }' "$SEEN" -)"
  if [ -n "$new" ]; then
    printf '%s\n' "$new" | awk 'NF { print $1" "$2 }' >> "$SEEN"
  fi
  if [ "$FIRST" = 1 ]; then
    FIRST=0
    if [ "$BASELINE" = 1 ]; then return 1; fi
  fi
  if [ -n "$new" ]; then
    printf '%s\n' "$new" | sed 's/^/NEW /'
    return 0
  fi
  return 1
}

if [ "$ONCE" = 1 ]; then poll; exit 0; fi
while true; do
  if poll && [ "$CONTINUOUS" = 0 ]; then exit 0; fi
  sleep "$INTERVAL"
done
