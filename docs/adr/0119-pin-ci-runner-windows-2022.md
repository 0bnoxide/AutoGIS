# ADR-0119: Pin CI runner to Windows 2022

**Status:** Accepted

**Date:** 2026-07-28

## Context

ADR-0110 introduced the repository's GitHub Actions test gate and selected
`windows-latest` to preserve Windows fidelity. The alias later selected the
`windows-2025-vs2026` hosted image without a repository decision. On that image,
a successful run took 477.15 seconds, including a 408.9-second progress stall
around one Matplotlib render test.

PR #387 evaluated a stable Windows image while parallelizing the arcpy-free
suite. Its final `windows-2022` run kept all render coverage on Windows and
completed 2,722 passing tests in 333.49 seconds. The render test still consumed
313.49 seconds and remains tracked by issue #388; the runner pin reduces
unreviewed image drift but is not presented as a complete fix for that test.

## Decision

Amend ADR-0110's runner selection: the arcpy-free CI job uses
**`windows-2022`**, not the floating `windows-latest` alias.

The job remains on Windows because the repository has Windows-path fixtures and
PowerShell/Windows coordination behavior. A future hosted-image migration must
be explicit and must run the full suite before replacing this pin.

## Consequences

### Positive consequences

- GitHub cannot move CI to a different Windows image without a workflow change.
- Pull requests retain the Windows coverage established by ADR-0110.
- Runner changes become reviewable and their timing can be compared against a
  named baseline.

### Negative consequences

- The pin requires maintenance when GitHub retires the Windows 2022 image.
- Pinning does not eliminate the hosted-Windows Matplotlib render bottleneck;
  issue #388 remains open.

## Alternatives considered

- **Keep `windows-latest`** — rejected because the floating alias already moved
  the suite to a new image without an AutoGIS decision.
- **Move the render checks to `ubuntu-latest`** — tested in PR #387 and rejected.
  The direct render passed, but the CLI render reproducibly exited with
  `MemoryError('std::bad_alloc')`; Linux remains an unverified platform for the
  Windows-native suite.
- **Use a self-hosted Windows runner** — rejected because its administration and
  security burden are not justified for this CI gate.

## Amendment (2026-07-30): pin moved to `windows-2025`

The anticipated maintenance case arrived one day after acceptance: from
~07:00 UTC on 2026-07-29 the `windows-2022` label stopped receiving runners.
Every job since fails in ~5 seconds with no runner assigned (`runner_id: 0`,
no logs, empty check-run output) — including the post-merge run of PR #387 on
`main` and the pytest checks on PRs #389 and #390. The same suite was green on
`windows-2022` at 06:53 UTC the same day, so this is image availability, not a
code regression.

The decision's substance is unchanged — the CI job stays on a **pinned, named
Windows image**, never the floating `windows-latest` alias. Only the pin value
moves: **`windows-2025`**. A full-suite `workflow_dispatch` validation run on
`windows-2025` preceded the change landing on any PR branch, satisfying this
ADR's migration requirement. The Matplotlib render slowness observed on this
image family remains tracked by issue #388.

## Related decisions

- [ADR-0110: GitHub Actions CI + arcpy-doc-verifier agent + next-adr preflight](0110-ci-and-agent-tooling-batch.md)
- [PR #387: Speed up Windows CI test suite](https://github.com/0bnoxide/AutoGIS/pull/387)
- [Issue #388: GitHub-hosted Windows takes 4-9 minutes for one Matplotlib render test](https://github.com/0bnoxide/AutoGIS/issues/388)
