# ADR-0107: GitHub Actions CI + arcpy-doc-verifier agent + next-adr preflight

**Status:** Proposed

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
  `pull_request` and pushes to `main`. Runner is **`windows-latest`**, not
  ubuntu: the repo is Windows-native (`C:\` path fixtures, PowerShell +
  Windows-path coordination logic) and the suite is demonstrably green there;
  ubuntu would be an unverified OS change layered on top of introducing CI.
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

## Consequences

### Positive consequences

- Branches are verified on GitHub before merge, independent of which machine
  authored them.
- The most-lapsed invariant (ADR-0077 arcpy currency) gets a repeatable,
  doc-citing check instead of relying on memory.
- ADR-number collisions are less frequent.

### Negative consequences

- windows-latest Actions minutes bill ~2× ubuntu; acceptable for this repo and
  it buys OS fidelity.
- The preflight **reduces, not eliminates** collisions: two sessions that both
  grab a number before either opens a PR are invisible to a PR scan. The `XXXX-`
  placeholder route (README) remains the belt-and-suspenders option — this very
  ADR used 0107 and may need renumbering at merge.

## Alternatives considered

- **ubuntu-latest CI** — cheaper, but the suite's Windows-path fixtures make
  Linux-cleanliness unverified; rejected to avoid changing OS and adding CI in
  one stroke.
- **A PreToolUse hook for arcpy edits** instead of a subagent — a shell hook
  can't read Esri docs or reason about deprecation; it could only nag. The
  subagent does the actual verification.
- **Hard-fail `next-adr` when `gh` is down** — rejected; degrades usability for
  no safety gain. Local-only scan is still an improvement.

## Related decisions

- [ADR-0077: arcpy API-currency policy](0077-arcpy-api-currency-policy.md) — the invariant the verifier enforces
- `docs/arcpy-official-references.md` — the versioned URL list the verifier cites (added separately, in a Codex PR)
- [ADR-0091: ArcGIS Pro qualification / release floor](0091-arcgis-pro-qualification-runner.md)
