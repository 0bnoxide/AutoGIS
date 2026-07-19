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

echo "OK: all watch-pr-reviews dedup/baseline checks passed"
