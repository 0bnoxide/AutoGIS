# ADR-0110: GitHub Actions CI + arcpy-doc-verifier agent + next-adr preflight

**Status:** Accepted

**Date:** 2026-07-23

## Context

An automation audit of this repo's Claude Code setup surfaced three gaps against
its own documented pain points:

1. **No CI.** `.github/workflows/` was empty. The ~2400-test arcpy-free suite ran
   only via a *local* PostToolUse hook, so nothing verified branches on GitHub
   before merge — and 4-5 concurrent sessions plus humans push here.
2. **arcpy API drift is unguarded.** ADR-0077 requires every arcpy call be
   doc-verified against current Esri docs, but the suite structurally cannot
   catch signature/enum/deprecation errors (arcpy seams are `pragma: no cover`);
   that is how #174/#214 shipped bad calls. The check was a manual discipline
   that kept lapsing.
3. **ADR-number collisions.** `new-adr` numbered only from merged local files, so
   concurrent sessions repeatedly picked the same NNNN and renumbered at merge
   (e.g. 0099 → 0105).

## Decision

Add three pieces of workflow tooling (no product/architecture code changes):

- **`.github/workflows/ci.yml`** — runs `pip install -e .[dev]` + `pytest` on
  `pull_request` and pushes to `main`. Runner is **Windows**, not ubuntu: the
  repo is Windows-native (`C:\` path fixtures, PowerShell + Windows-path
  coordination logic) and the suite is demonstrably green there; ubuntu would
  be an unverified OS change layered on top of introducing CI. ADR-0119 amends
  the original floating `windows-latest` selection to pin **`windows-2022`**.
  arcpy/arcgis stay uninstalled (core/adapters import without them by invariant;
  the extras are Pro-conda-only). gui and real-file tests self-skip
  (`importorskip("PySide6")`, `skipif(not path.exists())`).
- **`.claude/agents/arcpy-doc-verifier.md`** — a subagent that enumerates arcpy
  calls in a diff (including `.pyt` `Parameter` objects) and verifies each
  against `docs/arcpy-official-references.md`, applying the ADR-0077 dual check:
  valid at the Pro **3.6** runtime AND not deprecated at the Pro **3.5** floor.
  It enforces ADR-0077; it does not change it.
- **`.claude/skills/new-adr/next_adr_number.py`** — a preflight that numbers from
  local ADRs **and** open-PR diffs, failing soft to a local-only scan when `gh`
  is unavailable. `new-adr` step 1 now calls it.
- **`coord reserve-adr`** (`registry.reserve_number` + a `coord_cli` subcommand)
  — closes the pre-PR window the preflight can't: atomically claims the next free
  number in the **shared** coordination registry (`claims.json`), so a second
  session sees it immediately, before any PR exists. Reservations ride the
  existing TTL/heartbeat, so an abandoned one auto-reaps. `next_adr_number.py`
  honours live reservations too. Chosen over a star-in-filename convention
  (2026-07-23 user decision, PR #295 thread): a placeholder *filename* on an
  unmerged branch is invisible to other sessions — only a shared store closes
  the gap, and the repo already has one.

### Amendment — required ADR allocation enforcement (2026-08-13)

Issue #492 exposed that PRs #487 and #488 could both claim ADR 0129 despite
different slugs. Reservations remain the local pre-PR race defense, but this
amendment supersedes the original claim that reservation alone was sufficient;
it does not erase that decision's historical rationale. The pre-amendment
consequences below remain historical context, not the active workflow.

- A coordinated numeric ADR requires a verified, strict reservation. If session
  resolution or the strict GitHub scan is unavailable, `XXXX` is the explicit
  degraded draft state, not a competing allocator.
- Before a PR is ready, strict `--finalize` rewrites every placeholder's
  filename, H1, and index row; authors review the mapping, stage and commit it,
  then release reservations after merge.
- The paginated, fail-closed `adr-policy` check covers every PR, including
  human, remote, and fork PRs. The active default-branch ruleset must require
  that check.

### Amendment — SonarCloud CI analysis (2026-08-04)

- **`.github/workflows/build.yml`** runs the pinned SonarSource scanner on
  pushes to `main` and opened, synchronized, or reopened pull requests. It
  uses the existing **`windows-2022`** runner policy from ADR-0119 and the
  repository `SONAR_TOKEN` secret; the project key and organization are in
  `sonar-project.properties`.
- The SonarCloud project operator must keep **Automatic Analysis disabled**.
  Automatic Analysis and CI analysis cannot run together; the workflow scan is
  the authoritative analysis path because it is versioned, reviewable, and
  runs on pull requests before merge.
- Fork-originated pull requests skip the token-backed scan. GitHub does not
  pass repository secrets to fork workflows, so running the scanner there would
  fail with an empty token; same-repository pull requests and pushes to `main`
  continue to scan.

### Amendment — scan moved into the CI job, with coverage (2026-08-05)

Resolves issue #452. The scan-only design above produced no coverage report, so
SonarCloud's default **Coverage on New Code ≥ 80%** condition read 0.0% and
failed the quality gate on **every** pull request that added Python lines,
regardless of how well tested they were. That is a reporting gap, not a
coverage gap: PR #440 measured 95.2% coverage on its own added lines while the
gate showed 0.0%.

- **`build.yml` is deleted; the scan is now the last step of the existing
  `ci.yml` `pytest` job.** The suite runs once, with
  `--cov=autogis --cov-report=xml`, and the scanner reads that `coverage.xml`
  from the same workspace. `sonar-project.properties` gains
  `sonar.python.coverage.reportPaths=coverage.xml`; `pyproject.toml` gains
  `pytest-cov` in the `dev` extra and `[tool.coverage.run] relative_files =
  true` so the report's paths resolve independently of the checkout location.
- **Why not a second job.** Re-running the suite there would double the
  Windows minutes this ADR already flags as billing ~2×; passing the report
  between jobs as an artifact adds plumbing and a path-matching failure mode
  for no benefit. In-job also means a red suite no longer publishes metrics.
  Net cost is *lower* than the two-workflow arrangement it replaces, which
  span up a second Windows runner and checkout per PR.
- **Why not lower the gate instead.** That was the other option in #452 and it
  is free, but it is an external SonarCloud setting — unversioned, invisible in
  review, and it would have hidden real coverage regressions along with the
  false one. It remains available if the 80% threshold proves wrong against
  this repo's `pragma: no cover` arcpy surface (whole-repo coverage is ~79%,
  the shortfall concentrated in exactly those seams). The threshold itself is
  unchanged by this amendment.
- The `checkout` step now sets `fetch-depth: 0`, which the deleted workflow
  already did and which Sonar needs for new-code blame.
- **`sonar.sources=autogis` / `sonar.tests=tests` are part of the fix, not
  tidying.** With `sonar.sources` left at its `.` default, every added *test*
  line counts as new code needing coverage — and tests are not covered by
  `--cov=autogis`. Uploading coverage alone therefore moved PR #453 from 0.0%
  to 14.3%, not to the 95% its added production lines actually had: the PR
  added ~40 executable production lines and ~490 lines of regression tests, so
  the tests swamped the ratio. A well-tested change would have failed the gate
  *harder* the more tests it brought. `tests` stays declared as `sonar.tests`
  rather than excluded, so it is still analyzed for issues — it is just not
  held to a coverage threshold it cannot meet by construction.

### Amendment — the in-job scan is now time-bounded (2026-08-11)

Resolves the bounded half of issue #469. The amendment above moved the scan
into the `pytest` job for sound reasons, but had an unrecorded consequence: the
`pytest` check's conclusion became hostage to SonarScanner's reliability, and
nothing capped how long a hang could run. Both landed on PR #464 — the scanner
hung after its UCFG cache restore, the job ran to GitHub's 360-minute ceiling,
and a suite that had **passed** (`3008 passed, 15 skipped`) reported
`cancelled`. At windows-2022's 2× billing that single hang cost roughly what
~70 healthy runs of this job cost, silently.

- **`timeout-minutes: 30` on the `pytest` job.** The suite runs ~5-6 min; #388
  documents the slow Matplotlib render that dominates the tail.
- **`timeout-minutes: 10` on the SonarQube Scan step.** This is the
  load-bearing half: a step-level cap turns a silent multi-hour hang into a
  fast, clearly-attributed step failure, *after* the suite's own result is
  recorded. Healthy scans take ~3 min.
- **`continue-on-error` on the scan is deliberately NOT adopted here.**
  Decoupling the test verdict from Sonar's reliability would fix the
  false-`cancelled` reporting outright, but it also lets a genuinely broken
  scan pass unnoticed, and it reverses this ADR's own in-job placement
  rationale. That is an owner call; #469 stays open for it.
- **Ceiling.** A timeout cannot be proven to fire without reproducing the hang,
  which is intermittent by nature (the run immediately before #464's completed
  the identical scan in 2 min 48 s). The evidence here is the workflow parsing
  and running green, not an observed timeout.

## Consequences

### Positive consequences

- Branches are verified on GitHub before merge, independent of which machine
  authored them.
- The most-lapsed invariant (ADR-0077 arcpy currency) gets a repeatable,
  doc-citing check instead of relying on memory.
- ADR-number collisions are less frequent (preflight) and, when `reserve-adr` is
  used, prevented across live sessions before a PR exists.
- SonarCloud quality-gate analysis is versioned with the repository and runs
  against pull requests as well as `main`.

### Negative consequences

- Windows Actions minutes bill ~2× ubuntu; acceptable for this repo and they
  buy OS fidelity. The `windows-2022` pin added by ADR-0119 must be maintained
  when GitHub retires that image.
- The **preflight alone** reduces, not eliminates, collisions (the pre-PR window);
  `reserve-adr` closes that but only for sessions that opt to call it. This ADR
  proved the point live: it was first drafted as 0107, collided with PR #296 (also
  0107), and was renumbered to a `reserve-adr`-claimed **0110**.
- reserve-adr adds a new claim *kind* (`adr`) to the shared registry; it reuses
  the existing lock/TTL/reaping, so no new storage or lifecycle to maintain.
- A SonarCloud project administrator must maintain the one external setting
  that disables Automatic Analysis; enabling it makes the CI scanner fail.

## Alternatives considered

- **ubuntu-latest CI** — cheaper, but the suite's Windows-path fixtures make
  Linux-cleanliness unverified; rejected to avoid changing OS and adding CI in
  one stroke.
- **A PreToolUse hook for arcpy edits** instead of a subagent — a shell hook
  can't read Esri docs or reason about deprecation; it could only nag. The
  subagent does the actual verification.
- **Hard-fail `next-adr` when `gh` is down** — rejected; degrades usability for
  no safety gain. Local-only scan is still an improvement.
- **SonarCloud Automatic Analysis** — rejected because it conflicts with the
  CI scanner and does not make the analysis invocation reviewable in this
  repository.

## Related decisions

- [ADR-0077: arcpy API-currency policy](0077-arcpy-api-currency-policy.md) — the invariant the verifier enforces
- `docs/arcpy-official-references.md` — the versioned URL list the verifier cites (added separately, in a Codex PR)
- [ADR-0091: ArcGIS Pro qualification / release floor](0091-arcgis-pro-qualification-runner.md)
- [ADR-0119: Pin CI runner to Windows 2022](0119-pin-ci-runner-windows-2022.md) — amends the CI runner selection
