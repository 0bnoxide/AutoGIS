# Agent decisions — 2026-07-25

## Resume orphaned Survey123 slice A on a fresh branch

- **Decision:** Implemented the approved SampleID-contract spec on a new
  branch `worktree-survey123-sampleid-impl` (cherry-picking the spec commit
  `3dd3d9f` onto current main) instead of the original
  `worktree-survey123-sample-id-contract` worktree.
- **Reasoning:** The original worktree is locked by another live Claude
  session (pid 27576, started 2026-07-24) whose coordination claims had
  expired; the claims registry — the locking authority — showed the branch
  and files unclaimed, and the spec was already user-approved. Rebasing onto
  current main also picked up the 2026-07-25 housekeeping merges.
- **Revisit if:** the pid-27576 session resumes slice A — supersede via the
  collab channel and point it at the PR; retire the spec-only branch after
  merge.

## ADR numbered manually (0113)

- **Decision:** Chose ADR-0113 by inspection (highest on origin/main = 0112;
  the only open PR #338 carries no ADR) instead of `coord reserve-adr`.
- **Reasoning:** The canonical coordination CLI at the main tree root does
  not have the `reserve-adr` subcommand (main checkout is behind
  origin/main).
- **Revisit if:** another concurrent session opens an ADR-bearing PR before
  this one merges — renumber at merge per the established collision rule.

## Survey123 Phase 1 started and shipped in-session

- **Decision:** On the user's "continue" after slice A, designed and
  implemented Phase 1 (validate-survey-form + diff-survey-schema) with
  user-approved design/spec (AskUserQuestion approvals recorded in-session);
  based on merged main (053fe18), not the stacked branch the user originally
  chose, because #359 merged mid-design.
- **Reasoning:** the merge made stacking moot and picked up the review-forced
  QAFlags-based SampleID contract the validator must enforce.
- **Revisit if:** owner wants a different taxonomy severity (notably
  choice_removed=review vs choice_code_changed=destructive via the
  same-label heuristic) or true rename detection.

## ADR numbered 0115 (0114 taken mid-flight)

- **Decision:** ADR number chosen as 0115 after finding open PR #363 already
  claims 0114.
- **Reasoning:** highest on origin/main is 0113; ADR lessons require checking
  open PRs, which caught the collision.
- **Revisit if:** #363 closes without merging — do NOT renumber; gaps are
  cheaper than collisions.

## Survey123 Phase 2 branched from main, not stacked on Phase 1 (#364)

- **Decision:** Implemented Phase 2 slice 1 on
  `worktree-survey123-phase2-submission-sync` cut from `origin/main`, while
  Phase 1 (PR #364, ADR-0115) is still open.
- **Reasoning:** The user directed the Phase 2 start ("pickup phase 2 of
  survey123"). The puller/envelope shares no code with Phase 1's XLSForm
  validator, and a stacked PR risks the close-not-retarget hazard when the
  parent's head branch is deleted (documented lesson).
- **Revisit if:** merge order ever makes the CLAUDE.md gate-changes paragraph
  conflict — resolve by concatenating both phases' entries.

## Deletion detection: GlobalID sweep, not extractChanges

- **Decision:** Deletes are detected by diffing a full current-GlobalID query
  against the checkpoint's known-ID set, instead of the feature-service
  `extractChanges` API.
- **Reasoning:** The sweep works on any editor-tracked hosted layer;
  `extractChanges` needs the ChangeTracking capability enabled and a new,
  unverified API surface. Ceiling (noted in ADR-0116): a row added and
  deleted entirely between runs is never observed.
- **Revisit if:** surveys grow large enough that a full ID sweep per run is a
  real cost, or the between-runs blind spot matters — then `extractChanges`.

## Attachment metadata via harvester-verified get_list, per in-window feature

- **Decision:** `fetch_item_pulls` reuses `layer.attachments.get_list(oid=…)`
  (the harvester's shipped call) per in-window feature rather than the bulk
  `attachments.search()` API.
- **Reasoning:** get_list is already live-verified in this repo; the N+1 cost
  is bounded by the incremental window, not the layer size. search() would be
  a new call needing its own doc-verification for a marginal win.
- **Revisit if:** live QA shows attachment fetch dominating pull time.
