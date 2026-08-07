# Agent decisions — 2026-08-03

Session task: fix open issues by significance, check the README against actual
repo state, and survey the codebase for gaps and stale assertions. No live
owner was available, so every call below was made autonomously. ADR-0124 is the
durable record of the design decisions; this log records the judgment behind
them and the calls that did not warrant an ADR.

## Batch 16 issues into one PR rather than one PR per issue

**Decision:** Fix #416/#417/#419/#421/#422/#424/#426/#427/#428/#432/#433/#434/
#435/#437/#439/#442 in a single draft PR under one ADR.

**Reasoning:** They are one failure class — silent no-op / false success — and
several are the same defect at different layers, so reviewing them together is
what makes the pattern visible. Splitting into sixteen PRs would multiply the
review-gate overhead (a five-probe evidence matrix each) without adding signal.

**Revisit if:** The owner prefers per-issue review, or a reviewer finds the
diff too large to reason about in one pass — in which case #428 and the
GeoPackage trio are the clean split lines.

## Refuse a multi-matrix sampling plan instead of inferring one

**Decision:** `build_sampling_event_plan` raises on `len(matrices) > 1` (#421)
rather than planning the location × matrix × analyte_group cross-product.

**Reasoning:** The event-config schema has no per-analyte-group matrix mapping,
so the cross-product asserts a relationship the config never states. Both
failure directions cost field time: dropping matrices sends a crew without
bottles, over-planning sends them to collect soil at every monitoring well.
Refusing is the only option that does not invent domain semantics. The issue
author listed a loud failure as acceptable; the planner already raises on three
other malformed-config cases.

**Revisit if:** The event schema gains a per-group matrix mapping, or the owner
confirms the cross-product is the intended semantics.

## Constrain the GeoPackage `srs_id` parameter rather than remove or honor it

**Decision:** Keep the public `srs_id` parameter, reject anything but 4326
(#419).

**Reasoning:** Three options, and the middle one is the only honest one.
Honoring it needs reprojection and a CRS database — a different tool.
Removing it breaks the signature for callers passing the default explicitly.
Constraining states the exporter's one real contract without a signature
change; no caller in the repo passes anything else.

**Revisit if:** The exporter grows reprojection, at which point the constraint
becomes the thing to lift.

## Report the destructive state instead of building rollback (#428)

**Decision:** Promote rejected adds to blocking failures and name the resulting
hosted state, rather than implement staging/swap or query-before-truncate.

**Reasoning:** Rollback machinery for a live portal cannot be exercised
headlessly, so it would ship untested against the exact scenario it exists for.
The recovery being documented is real rather than a disclaimer — the local mart
holds every row and each refresh rebuilds the table from it.

**Revisit if:** A live-portal QA leg becomes available, or an operator hits the
partial state often enough that manual re-run is not acceptable.

## Fix the `autogis-harvest` entry point rather than the README sentence

**Decision:** Repoint the console script at `harvest_cmd` (#442) instead of
rewording the README to describe the broken behavior.

**Reasoning:** The alias exists solely for backward compatibility and was
fulfilling none of it. Documenting that is documenting the defect. This is a
behavior change to a shipped console script made without owner input, which is
why it is called out here as well as in ADR-0124 — the mitigating facts are
that the current behavior is a duplicate of `autogis` (so nothing unique is
lost) and that the git history shows the regression point.

**Revisit if:** Anyone is relying on `autogis-harvest <subcommand>` as a second
name for the full CLI.

## Rewrite one existing test rather than special-case the fix around it

**Decision:** `test_reconcile_event_plan_analyte_group_scalar_is_unresolved_not_chars`
asserted downstream tolerance that existed *because* of #437. Split it into an
upstream-rejection test and an empty-member-list test rather than weaken the
#437 fix to keep it green.

**Reasoning:** The test encoded the bug's consequence as the contract. The
reconciler's own fallback still needed coverage, though — an empty member list
is a shape the planner still accepts — so the branch is kept under test rather
than dropped.

**Revisit if:** The empty-group shape should also be rejected upstream, which
would make the second test redundant.

## Survey the repo with read-only subagents, then verify every finding myself

**Decision:** Two parallel read-only subagents (README audit, wiring-gap
survey); no finding filed or acted on without independently reproducing it.

**Reasoning:** This paid for itself immediately — the README audit reported the
production roadmap's gate log as missing its 2026-07-30 Phase 5 entry, and the
entry is present at `docs/production-roadmap.md:199`. That correction was
dropped rather than "fixed". Every other finding was confirmed by grep/read
before it became an issue or a commit.

**Revisit if:** Never — verify before filing is the standing rule.

## File eight survey findings as issues rather than fixing them in this PR

**Decision:** #443–#450 filed, not fixed. #441 likewise.

**Reasoning:** Most require an arcpy seam (`pragma: no cover`) or a decision
about which config surface owns a key — neither is provable by the headless
suite, and #444/#446/#447 need ADR-0077 doc-verified arcpy work in a session
with Pro available. Fixing them here would have added unverifiable changes to a
PR whose whole claim is that every fix is tested.

**Revisit if:** A Pro-equipped session picks up the `.pyt` cluster
(#444/#446/#447) as one batch, which is how they should be fixed.

## Backfill the Survey123 Phase 3 gate-log entry

**Decision:** Add the missing 2026-08-02 Phase 3 entry to the roadmap's
Gate-change log and to CLAUDE.md's current-state line.

**Reasoning:** This is bookkeeping of an event that already happened
(ADR-0123, PR #438 merged), not a gate decision — which remains an owner call.
The entry says so explicitly: the phase shipped, the gate is *not* closed, and
ADR-0123 is still Proposed pending its owner-gated end-to-end leg. Leaving the
log silent was the greater risk, since CLAUDE.md designates it as the authority
and it disagreed with both the README and the merged code.

**Revisit if:** The owner considers a shipped-but-ungated phase to belong
somewhere other than the gate log.
