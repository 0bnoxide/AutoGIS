# ADR-0124: Silent-failure fix batch (2026-08-03) — fail loudly at the seam that knows

**Status:** Proposed

**Date:** 2026-08-03

## Context

A repo-wide audit session (2026-08-02) and the cold review of PR #438 filed a
cluster of open issues that share one failure class: the code did something
plausible instead of saying it could not do the right thing. None of them
raised, crashed, or logged; each produced an output an operator would read as
success.

- **#434** `load_flat_screening_levels` treated a screening-levels file as
  matrix-nested if *any* top-level value was a dict, so a mixed file silently
  flattened to `{}` — a regulatory surface with no levels reports no
  exceedances anywhere.
- **#421** `build_sampling_event_plan` read the whole `matrices` list and used
  only `matrices[0]`. A crew was dispatched with no bottles for the dropped
  matrix; the gap resurfaced days later as `matrix_mismatch` errors on the lab
  side, where nobody could trace it back to planning.
- **#437** a YAML scalar under an analyte group (`VOC: Benzene`) skipped the
  analyte-dictionary validation the function otherwise enforces.
- **#422** `records_from_plan` counted plan *rows*, but the planner emits one
  row per (location × analyte_group) sharing a sample ID — the COC audit trail
  claimed more planned samples than `reconcile()` could ever match.
- **#439** `load_survey123_csv_submissions` let a cp1252 export escape as a raw
  `UnicodeDecodeError` out of the codec, through every consuming CLI.
- **#433** `get_logger`'s configure-once short-circuit dropped a later call's
  `logfile`, and never set `propagate = False`.
- **#432** `run_history._load` demanded a writable handle even off Windows,
  where the sentinel lock is a documented no-op (ADR-0051).
- **#435** `densify_polyline` divided by the raw minimum segment length, so one
  duplicate vertex made spacing `0` and returned the input undensified.
- **#427** `assemble_figure_package` resolved an unknown role to the package
  root via `_ROLE_SUBDIR.get(role, ".")`, keeping the invalid role in the
  manifest and exiting 0.
- **#426** the advertised `source_gdb` role always crashed — an Esri file
  geodatabase is a directory and `shutil.copy2()` cannot copy one.
- **#424** `refresh_dashboard_data` iterated an empty mart and reported
  `tables_refreshed=0 rows_pushed={} failures=[]` at exit 0, indistinguishable
  from a real refresh.

Two of these needed a judgment call rather than a mechanical fix, and that is
what this ADR records.

## Decision

**1. Fix at the seam that has the information, not at each caller.** #439 is
the shape of the rule: the loader is shared by `route-survey123`,
`sync-survey123`, `reconcile-survey123-lab` and `reconcile-event`, and PR #438
had already guarded one of them. The loader now normalizes decode, CSV and OS
read failures into a `ValueError` naming the file; the CLI seams translate that
to a `ClickException`. Future consumers inherit the clean error instead of
re-deriving the guard. The loader stays strict UTF-8 — `errors="replace"` would
corrupt well and sample IDs silently, which is the same defect one layer down.

**2. Refuse rather than guess when the schema cannot express the intent
(#421).** A multi-matrix plan needs a per-analyte-group matrix mapping that the
event-config schema does not have. Two wrong answers were available: keep
dropping matrices silently, or invent a location × matrix × group cross-product
that would dispatch a crew to collect soil at every monitoring well.
`build_sampling_event_plan` now raises `ValueError` naming every declared
matrix and pointing at one event config per matrix. This is a deliberate
behavior break: a config that "worked" now fails. It was producing an incorrect
plan, and the planner already raises on unknown analytes, empty `location_ids`
and empty `crew_list` — refusing a plan it cannot build correctly is that same
contract. `survey123_form_builder` continues to offer the full matrix list as a
form choice; the form lets the crew pick a matrix, the plan pins one.

**3. Validate an advertised contract, or do not advertise it (#427, #426).**
`DELIVERABLE_ROLES` is public, so every role in it must resolve to a
destination: role validation moved into the preflight, before any package
mutation, and `_ROLE_SUBDIR` is now indexed directly so a role added to one and
not the other is a loud `KeyError` rather than a silent copy to the package
root. `source_gdb` is likewise honored rather than withdrawn — directory
sources are packaged with `copytree`, and the manifest carries a deterministic
content-addressed digest (sorted POSIX-relative path + per-file digest), so a
`.gdb` row means the same thing as a file row.

**4. An empty input set is a failure, not a successful no-op (#424).** The
guard lives in `refresh_dashboard_data` so direct core callers get it too; the
CLI checks the mart directory *before* authenticating, so a doomed run never
reaches AGOL.

## Consequences

### Positive consequences

- Every fix converts a false success into a diagnosable failure at the layer
  that knows why.
- #434 closes a regulatory false-negative of the same class as #339/#341.
- #426 makes `source_gdb` a working role for the first time.
- Each fix carries a regression test; the arcpy-free suite covers all eleven
  (no arcpy seam was touched, so nothing landed under `pragma: no cover`).

### Negative consequences

- **#421 and #437 are behavior breaks.** Event configs with multiple matrices,
  or with a scalar analyte-group value, now fail where they previously produced
  a partial or unvalidated plan. Both were producing wrong output; the break is
  the point, but a site with a multi-matrix config must split it.
- **#427 is a behavior break** for specs carrying a misspelled role — those
  packages previously built with the file at the root.
- `get_logger` no longer propagates, so a host application that expected to
  capture AutoGIS records through a root handler must attach to the AutoGIS
  logger instead. No caller in this repo relied on propagation.
- Directory deliverables make packaging time and size proportional to the
  geodatabase, and the digest reads every contained file.

## Alternatives considered

- **#421, honor the list** by planning the location × matrix × analyte_group
  cross-product. Rejected: over-planning is also a field-cost error, and the
  cross-product asserts a matrix/group relationship the config never states.
- **#421, QA warning instead of raising.** `build_sampling_event_plan` takes no
  `QACollector`; adding one to carry a single warning is more plumbing than the
  refusal, and a warning on a plan the crew will act on is easy to miss.
- **#439, normalize inside the loader with `errors="replace"`.** Rejected —
  silently corrupts identifiers.
- **#439, guard at each CLI call site only** (the PR #438 pattern). Rejected:
  leaves the next consumer to rediscover it.
- **#426, reject `source_gdb` with guidance to supply an archive.** Rejected —
  the role is advertised; withdrawing it is a documentation fix for a
  capability gap.
- **#432, drop the lock entirely off Windows.** Already the case (ADR-0051);
  only the open mode needed to follow.

## Related decisions

- [ADR-0051: run-history sentinel locking](0051-run-history-msvcrt-sentinel-lock.md)
- [ADR-0122: Report-package integrity and dashboard JSON bridge](0122-report-package-integrity-and-dashboard-json-bridge.md)
- [ADR-0123: Survey123 Phase 3 event reconciliation](0123-survey123-phase3-event-reconciliation.md)
- Issues [#421](https://github.com/0bnoxide/AutoGIS/issues/421),
  [#422](https://github.com/0bnoxide/AutoGIS/issues/422),
  [#424](https://github.com/0bnoxide/AutoGIS/issues/424),
  [#426](https://github.com/0bnoxide/AutoGIS/issues/426),
  [#427](https://github.com/0bnoxide/AutoGIS/issues/427),
  [#432](https://github.com/0bnoxide/AutoGIS/issues/432),
  [#433](https://github.com/0bnoxide/AutoGIS/issues/433),
  [#434](https://github.com/0bnoxide/AutoGIS/issues/434),
  [#435](https://github.com/0bnoxide/AutoGIS/issues/435),
  [#437](https://github.com/0bnoxide/AutoGIS/issues/437),
  [#439](https://github.com/0bnoxide/AutoGIS/issues/439)
