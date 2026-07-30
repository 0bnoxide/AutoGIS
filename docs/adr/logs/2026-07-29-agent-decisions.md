# Agent decision log — 2026-07-29

Autonomous judgment calls made during a scheduled maintenance session
(fix open issues by significance, README staleness check, structural survey).
Supplements ADR-0120; does not replace it.

Session branch: `claude/stoic-fermat-ctg2km` · PR #390 (draft).

---

## 1. #339 — took a design decision the issue explicitly reserved for the owner

**The call.** Issue #339's "Fix direction" section says *"Pick one (owner call —
this is a design decision, not a one-line fix)"* and lists three options. No
owner was available (scheduled, unattended session). I implemented a variant of
**option 2** (report modules accept the canonical vocabulary) rather than
leaving the issue untouched, and folded in part of **option 3**.

**What I built, and why not literally option 2.** Option 2 as written — "have
the report modules accept `AnalyticalResultRecord` directly like their siblings
do" — is a rewrite of every field read across eight modules plus their fixtures,
and it would break any user CSV already in the report vocabulary. I implemented
it instead as a **widening**: `normalize_report_rows()` backfills the report
vocabulary from the canonical one at each builder's entry point, so both
vocabularies work and the report one keeps winning when explicitly present. Same
correctness outcome, far smaller blast radius, and the full rename stays
available later behind one alias table.

I rejected **option 1** (add a canonical→report exporter) outright: it creates a
producer for a convention that has no reason to exist, and does nothing for the
canonical CSVs already written.

From **option 3** I kept the part that is strictly additive — a QA `WARNING`
when a row set carries *neither* vocabulary. I did **not** implement its
header-validation-and-reject behavior, because after the widening a canonical
CSV is no longer a mismatch to reject.

**Why not defer.** The defect is a silent false negative on exceedance detection
in a regulatory-compliance tool, with a confirmed repro. Leaving it open for an
unbounded wait seemed worse than shipping a reversible, test-pinned fix behind a
draft PR the owner reviews before merge.

**How to redirect.** Everything hinges on `REPORT_FIELD_ALIASES` in
`autogis/core/envmon/report_input.py`. Preferring option 1 or the literal option
2 means deleting that module and its eight call sites — a clean revert, not an
unpick. Flagged on the issue and in the PR body.

## 2. #376 — validate in core, and fail loud rather than warn

Two sub-calls, neither specified by the issue:

- **Core, not click options.** `click.DateTime` would have been the smaller
  change, but both issues' reproduction cases call the builders directly, so
  option-level validation leaves every programmatic caller exposed. Put the
  guard where all callers converge.
- **Raise, don't warn.** A malformed date means the run's entire output is
  already wrong, and `--report` is optional so a QA warning could go unread.
  Exit-code failure is the honest signal. This is a behavior change for anyone
  who was (silently, wrongly) passing a malformed date and getting exit 0.

Also chose **round-trip equality** over bare `fromisoformat` success, because
3.11+ accepts `20260701` — parses fine, compares wrong against the hyphenated
`SampleDate`. Bare `fromisoformat` would have left a real hole open.

## 3. #374 — skipped the test off-Windows rather than making the lock portable

The issue offered two directions and left the call open. Took option 1 (skip
off-Windows). Option 2 (make the lock cross-platform via `fcntl`) would mean
implementing real concurrency protection on a platform ADR-0051 deliberately
declined to support, for a Windows/SMB-only deployment target — new production
code to make a test green, which inverts the cost. The skip is annotated with
the full reason so it reads as a documented platform boundary, not a silenced
failure.

**Ceiling:** off-Windows contributors get no coverage of the run-history race.
That is unchanged from before — the test was ~1-in-3 flaky there, i.e. it was
already not providing coverage, only noise.

## 4. Closed five issues fixed by PR #373 but left open

#340, #341, #342, #343, #345 were all fixed and merged in fcdc72f (PR #373),
which carried no `Closes` trailers in its body. I verified each against the
code and its regression test on current `main` before closing — not against the
commit message, which is the failure mode that produced #219/#220 (issues closed
by a trailer on a branch that never merged; the inverse error, but the same root
cause of trusting a message over the tree).

Each close carries a comment citing the specific file:line and test that
discharges it, so the verification is auditable rather than asserted.

## 5. Scope held: three issues deliberately not fixed

#220, #344 and #361 are real and open, and I left them alone on purpose — each
needs a decision no code change can substitute for (a blocking-severity policy
plus a `SOIL` `data_type` wiring gap; a GDB schema column addition; a SampleID
discriminator scheme). Written up in the session's final report for the owner
rather than guessed at. Filing a fix for these would have meant inventing a
requirement.
