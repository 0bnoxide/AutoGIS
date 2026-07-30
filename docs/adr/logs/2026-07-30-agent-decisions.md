# Agent decisions — 2026-07-30

## CI runner pin moved to `windows-2025` and applied directly to open PR branches

- **Decision:** Diagnosed the instant CI failures on PRs #389/#390 (and the
  post-merge run of #387 on `main`) as the `windows-2022` hosted image no
  longer receiving runners as of ~07:00 UTC 2026-07-29. Moved the ADR-0119 pin
  to `windows-2025`, validated with a full-suite `workflow_dispatch` run on a
  side branch first, then cherry-picked the same commit onto both open PR
  branches so their pytest checks can go green.
- **Reasoning:** Failed jobs show `runner_id: 0`, no logs, empty check-run
  output, and a ~5-second lifetime — a runner-assignment failure, not a test
  failure; the identical suite passed on `windows-2022` at 06:53 UTC the same
  day. `windows-2025` is the only remaining GitHub-hosted Windows image, and
  ADR-0119 already rejected both `windows-latest` (floating) and Ubuntu
  (unverified platform, CLI-render `MemoryError`). Committing to the PR
  branches directly was the user's explicit request ("issue commits to fix");
  `main` inherits the fix when either PR merges. Amended ADR-0119 in place
  rather than writing a new ADR: the decision (pin a named image) is
  unchanged, only the pin value moved — the exact maintenance case the ADR
  predicted.
- **Revisit if:** GitHub announces `windows-2025` retirement or a
  `windows-2026` image, or issue #388's render bottleneck justifies
  re-evaluating the image choice.
