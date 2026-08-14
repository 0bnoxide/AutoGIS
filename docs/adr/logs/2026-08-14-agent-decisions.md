# Agent decisions — 2026-08-14

Session: PR #497 conflict resolution + five-issue fix batch (#496 #499 #495
#476 #500). ADR: `XXXX-issue-fix-batch-2026-08-14.md`. Supplement to that ADR,
not a substitute.

## PR #497 conflict resolution on a detached HEAD

The PR branch was checked out in another live session's claimed worktree, so
the merge of origin/main was done on a detached HEAD in this session's own
worktree and pushed to the PR ref — no other session's tree touched. The ADR
index conflict was resolved by keeping main's 0129/0130 rows AND the PR's
`XXXX` row, deliberately NOT renumbering: PR #494 was still open with its own
placeholder, and renumber-at-merge is the documented convention. Harvester
conflict resolved as the union of both intents (geometry/checksum fill +
`_warn_unresolved_template_fields`), standardizing on main's `log` name.

## Batch shape

Five fixes = one PR (ADR-0124/0125 precedent) instead of five PRs. #500 was
planned as a PR stacked on #494's branch (its target code existed only
there); #494 merged mid-session, so the fix folded into this batch — the
stacked-PR plan was dropped, not carried out.

## Judgment calls inside the fixes

- **#476:** the `8.2a` sub-tool (TransformLandXMLSurface) followed its parent
  section to `8.10a` — not in the issue, but leaving it would have attached
  the sub-tool to the level-loop section's number. Historical ADRs, decision
  logs, and dated snapshots keep the old numbers (accurate at time of
  writing). The `_ROADMAP_COLUMN_EXEMPT` rtk entries stay: removing them
  means populating empty roadmap_ids, which is #477's scope.
- **#500:** dropped the issue sketch's pre-`unlink` of the destination before
  `os.replace` — `os.replace` overwrites atomically on Windows and the
  pre-unlink would reopen the destroy-then-fail window the fix closes.
- **#495:** a failed `git fetch` still reads the stale local `origin/main`
  ref as a floor (with the warning) — a stale floor beats none; only a fully
  unreadable remote ref degrades to local-trees-only.
- **#496:** the residual on PR #497 (photo consumers must catch the new
  `ValueError`) was recorded as a PR #497 comment rather than an issue — it
  is only a defect once both PRs merge, and the comment reaches the branch
  owner before that point.
