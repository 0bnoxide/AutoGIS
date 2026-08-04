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
