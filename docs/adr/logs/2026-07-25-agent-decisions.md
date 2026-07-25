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
