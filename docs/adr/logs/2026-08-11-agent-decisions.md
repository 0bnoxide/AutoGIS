# Agent decisions — 2026-08-11

Session: interactive run ("fix a batch of issues" — batch selection delegated to
the agent). Branch `worktree-fix-batch-headless-wiring`.
The one design decision is recorded as a third amendment to **ADR-0110**; this
log records the autonomous *judgment calls* it does not, per
`docs/adr/logs/README.md`.

## Scope calls

**Shipped a two-issue batch: #436 and #469.** "A batch" was read as "everything
currently fixable and unclaimed", not as a headcount. Partitioning the 25 open
issues gave: 6 already claimed by open PR #467, 5 owner-call, ~10 QA/live-gated,
2 blocked behind #467, 1 large multi-part (#465), and exactly these 2 available.
A thin batch that adds no conflicts beat a padded one.

**Discovered mid-session that PR #467 already closes six issues I had begun
fixing (#459, #460, #461, #462, #463, #466) — and deleted that work rather than
reconciling it.** The overlap was found while numbering the ADR: #467 claims
`docs/adr/0127-…`, whose title (`…mart-key-resolution…`) prompted reading its
body. #467's versions are strictly better — it pins #466 against `TABLE_SCHEMAS`
so the wrong column name cannot come back, tests the selector→builder seam, and
also fixes #463 item 2, which I had excluded as arcpy-touching. Eight files were
reverted; the branch is now disjoint from #467 by file, not merely by intent.
**Lesson worth keeping: check open PRs for issue claims *before* writing, not at
ADR-numbering time.** `gh pr list` at session start showed #467's title but not
its `Closes:` list, which is where the claims actually live.

**Did not stack #470/#471 on PR #467.** Both are gen-map-series defects that
#467's cold review surfaced and left unfixed, so #467 is their natural base —
but it is open with no review decision, and its refactor rewrites the very
function (`gen_map_series_cmd`) they land in. Writing against a head that is
both unreviewed and about to change shape trades a small gain for a rebase
hazard the repo has already been bitten by (stacked-PR retarget). Left as
follow-ups for after #467 merges.

**Left the owner-call issues alone** — #468 (whether `DRAFT` belongs in the
`--runtime` Choice at all), #458 (renumber six tools vs. drop the duplicated
`Tool N.N` prose), #449/#450 (wire-or-delete on shipped config keys). Each issue
says in its own text that the fix requires a decision rather than a correction.
#465 (six structural-machinery defects) is a multi-PR program, not a batch item.

## Judgment calls inside the fixes

**#469 — took the timeout half, refused the `continue-on-error` half.** The
issue offers both. Bounding the runtime is unambiguous and purely protective.
Decoupling the test verdict from Sonar's result is a real trade (a broken scan
would then pass unnoticed) and reverses ADR-0110's own in-job-placement
rationale, so it is the owner's. **#469 is therefore left open** — the PR says
"addresses", not "closes".

**#469 — amended ADR-0110 instead of minting ADR-0128.** The change revisits
that ADR's subject matter directly, and it already carries two amendment
sections, so a third is the established shape. ADR-0128 remains free.

**#436 — took the one-line `None` return, not the consolidation.** The issue's
"fix direction" is to merge the three divergent RPD implementations into one.
That is a refactor across three modules to remove a latent defect with **zero
production callers** (`classify_qc_rows` always emits `rpd=None`). Fixed the
divergence; left the consolidation, and said so on the issue.

**#436 — the test asserts cross-implementation agreement, not just the new
return.** `compute_rpd` has no production call site to probe, so the honest
evidence that the contract is right is that all three implementations now
answer identically on the zero-mean case. A test asserting only
`compute_rpd(0.0, 0.0) is None` would pass just as well if the siblings drifted
the other way.

## A non-finding worth recording

**The five `test_sync_ponytail_skills.py` failures seen through most of this
session were an artifact of a stale branch base, not a defect.** `EnterWorktree`
branched from a HEAD seven commits behind `origin/main`; PR #464 had already
fixed them (issue #455, closed). Caught by rebasing before writing the PR — the
suite went from `5 failed, 3111 passed` to `3139 passed, 0 failed` with no code
change. No issue filed. Worth noting because the failures looked like a
plausible standing environment gotcha (WSL-stub bash) and were nearly reported
as one.
