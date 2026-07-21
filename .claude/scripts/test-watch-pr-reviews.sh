#!/bin/bash
# test-watch-pr-reviews.sh — self-check for watch-pr-reviews.sh dedup/baseline
# logic (#261), using a stubbed `gh` on PATH. No network, no real repo.
# Run: bash .claude/scripts/test-watch-pr-reviews.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT

mkdir "$T/bin" "$T/fix"
export FIX="$T/fix"
cat > "$T/bin/gh" <<'EOF'
#!/bin/bash
case "$*" in
  *"/pulls/7/reviews"*)   cat "$FIX/reviews.txt" ;;
  *"/pulls/7/comments"*)  cat "$FIX/inline.txt" ;;
  *"/issues/7/comments"*) cat "$FIX/issue.txt" ;;
  *) echo "unexpected gh call: $*" >&2; exit 1 ;;
esac
EOF
chmod +x "$T/bin/gh"
export PATH="$T/bin:$PATH"

run() { bash "$HERE/watch-pr-reviews.sh" 7 --repo o/r --include-self --once --seen-file "$T/seen" "$@"; }
fail() { echo "FAIL: $1"; exit 1; }

printf 'REVIEW 2 bob APPROVED\n' > "$FIX/reviews.txt"
printf 'INLINE 1 alice f.py:10\n' > "$FIX/inline.txt"
: > "$FIX/issue.txt"

out="$(run)"
[ "$out" = 'NEW INLINE 1 alice f.py:10
NEW REVIEW 2 bob APPROVED' ] || fail "first poll should emit both items, got: $out"

out="$(run)"
[ -z "$out" ] || fail "unchanged repeat poll re-emitted: $out"

# The #261 regression: a push lands on the PR and GitHub recalculates the
# inline comment's line — same id, different display string — must NOT re-emit.
printf 'INLINE 1 alice f.py:99\n' > "$FIX/inline.txt"
out="$(run)"
[ -z "$out" ] || fail "line-churn on a seen id re-emitted: $out"

# A temporarily short API response must not erase an item's identity and
# resurrect it when the item returns on a later poll.
: > "$FIX/inline.txt"
out="$(run)"
[ -z "$out" ] || fail "short response emitted an item: $out"
printf 'INLINE 1 alice f.py:99\n' > "$FIX/inline.txt"
out="$(run)"
[ -z "$out" ] || fail "item resurrected after a short response: $out"

printf 'INLINE 1 alice f.py:99\nINLINE 3 carol g.py:5\n' > "$FIX/inline.txt"
out="$(run)"
[ "$out" = 'NEW INLINE 3 carol g.py:5' ] || fail "genuinely new item, got: $out"

# --baseline swallows pre-existing items; a later run emits only what's new.
rm "$T/seen"
out="$(run --baseline)"
[ -z "$out" ] || fail "--baseline emitted pre-existing items: $out"
printf 'ISSUE 9 dave\n' > "$FIX/issue.txt"
out="$(run)"
[ "$out" = 'NEW ISSUE 9 dave' ] || fail "post-baseline new item, got: $out"

# --baseline keys off seen-file freshness: a FRESH seen-file is baselined
# (swallowed), but re-arming the same command against an EXISTING seen-file must
# FIRE the gap -- a review that landed while a torn-down Monitor was offline --
# not swallow it silently.
rm -f "$T/seen"
printf 'REVIEW 2 bob APPROVED\n' > "$FIX/reviews.txt"
: > "$FIX/inline.txt"; : > "$FIX/issue.txt"
out="$(run --baseline)"
[ -z "$out" ] || fail "fresh --baseline should swallow pre-existing, got: $out"
printf 'REVIEW 2 bob APPROVED\nREVIEW 5 codex COMMENTED\n' > "$FIX/reviews.txt"
out="$(run --baseline)"
[ "$out" = 'NEW REVIEW 5 codex COMMENTED' ] \
  || fail "re-arm --baseline swallowed the gap instead of firing it, got: $out"

# --reviews-only ignores the conversation timeline (self/user replies share the
# owner login) but still surfaces reviews.
rm -f "$T/seen"
printf 'REVIEW 2 bob APPROVED\n' > "$FIX/reviews.txt"
: > "$FIX/inline.txt"
printf 'ISSUE 9 dave\n' > "$FIX/issue.txt"
out="$(run --reviews-only)"
[ "$out" = 'NEW REVIEW 2 bob APPROVED' ] \
  || fail "--reviews-only should emit only the review, got: $out"

help="$(bash "$HERE/watch-pr-reviews.sh" --help)"
[[ "$help" != *'set -uo pipefail'* ]] || fail "--help leaked executable code"

if out="$(run --seen-file --continuous 2>&1)"; then
  fail "--seen-file accepted a missing PATH"
fi
[[ "$out" = *'--seen-file requires PATH'* ]] || fail "missing PATH diagnostic: $out"

if out="$(run --seen-file "$T/missing/seen" 2>&1)"; then
  fail "unwritable --seen-file exited successfully"
fi
[[ "$out" = *'POLL-FAIL'*'cannot write seen-file'* ]] || fail "unwritable seen-file diagnostic: $out"

echo "OK: all watch-pr-reviews dedup/baseline checks passed"
