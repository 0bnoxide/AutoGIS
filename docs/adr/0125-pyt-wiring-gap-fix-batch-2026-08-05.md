# ADR-0125: Wiring-gap fix batch — dead `.pyt` parameters, unfed QA collectors, inert figure-spec keys, and the CI coverage gate

**Status:** Proposed

**Date:** 2026-08-05

## Context

The 2026-08-03 repo-wide wiring-gap survey (recorded in PR #440, which fixed a
different batch) filed nine findings it deliberately did not fix. Six of them,
plus the CI gate blocking every PR from merging, are the subject of this batch:

| Issue | The gap |
|---|---|
| #452 | SonarCloud's quality gate failed **every** PR — the scan ran with no coverage report, so "Coverage on New Code" was always 0.0% |
| #447 | Five of 21 `.pyt` tools had no `@record_pyt_run`, so their Pro runs were invisible to `evaluate-readiness` / `portfolio-metrics` (ADR-0068 non-compliance) |
| #446 | `.pyt` `FullPipeline` **required** an "Export folder" parameter `execute()` never read |
| #443 | `generate_callouts: false` and the entire `contours:` block of the shipped potentiometric figure spec were read by nothing |
| #445 | `plausible_gwe_range_ft` was required on the site config and read only from the parser profile, whose `init-site` template omits it |
| #444 | `_write_contour_points` dropped the `QACollector` it was handed and returned silently on a pre-upgrade geodatabase |
| #431 | `.pyt` `HarvestAttachments` constructed a `QACollector`, passed it to nothing, and reported only "N attachment(s) processed" |
| #448 | Dead `load_screening_levels_yaml` sat beside the canonical loader and would `TypeError` on the shipped nested `screening_levels.yaml` |
| #441 | `tests/envmon/test_landxml_transform.py` hard-failed (18 errors) without the optional `[landxml]` extra instead of skipping |

Everything except #452 and #441 is one failure class: **something declared or
constructed and then never read.** None of it raises. All of it reads as
working — a required parameter the user must fill in and that is discarded, a
QA channel that is always empty, config that is authoritative-looking and
inert.

## Decision

### 1. Honor what is declared; delete what cannot be honored

- **#443 — `generate_callouts` is honored inside
  `generate_callout_features`,** not at each call site. Both existing callers
  (`.pyt` Tool 3 and `FullPipeline`) and any future one now obey the spec from
  one guard. It is checked *before* the function reaches `_arcpy()`, which is
  what makes the behavior testable headlessly.
- **#443 — the `contours:` block is mapped by
  `toolbox_core.spec_contour_kwargs()`** to `build_groundwater_contours`
  keyword arguments, and `FullPipeline` calls the function through it. Only
  keys the spec actually supplies are passed, so the core function's defaults
  remain the single source of truth. An unusable value (unknown method,
  non-numeric interval, non-mapping block) raises `ValueError` rather than
  falling back silently — a silent fallback would recreate the defect.
  Tool 5's own `.pyt` parameters are explicit user input and are unchanged.
- **#446 — the unread `export_dir` parameter is removed** rather than wired.
  `FullPipeline` deliberately stops before export and tells the operator to run
  Tool 6, which owns that parameter; the requirement was blocking runs on a
  value the tool then threw away.
- **#445 — the site config owns `plausible_gwe_range_ft`; the parser profile
  no longer does.** The issue left the direction open. The site config wins on
  every axis but the one line of code: the value describes a site's AMSL
  elevation band, not a workbook's layout; `config_validation` already
  *requires and type-checks* it there; `site.yaml`'s own comment documents the
  QA-ERROR behavior; and `init-site`'s parser-profile template has never
  carried the key, so every freshly initialized site had the filter silently
  disabled. `normalize_gw_table_2` takes the range as a parameter and
  `run_import` passes `site_config.get("plausible_gwe_range_ft")`; the
  duplicate in the shipped H281 parser profile is removed so only one file
  claims it.
- **#448 — `load_screening_levels_yaml` is deleted.**
  `config.load_flat_screening_levels` is the canonical loader for that
  argument, handles both the flat and shipped-nested shapes, and the dead one
  raised `TypeError` on the shipped file. Nothing but its own test called it.

### 2. Feed the QA collectors that already exist

- **#444** — a missing `Env_GWContourPoints` now emits a WARNING through the
  `qa` the function was already being handed, naming the feature class and
  pointing at `envmon upgrade-schema`. Contouring still proceeds; it just is no
  longer silent about the figure layer that will render empty.
- **#431** — `toolbox_core.run_harvest()` takes an optional `qa` and records
  every failed attachment plus a disposition summary. `harvest()` deliberately
  never kills a run over one bad attachment (that resilience is correct), which
  is precisely why the failures need a reporting channel. `qa` is optional, so
  the CLI path is untouched.

### 3. Record every `.pyt` run

**#447** — the five undecorated tools (`HarvestAttachments`,
`InspectWorkbook`, `ReadParserProfile`, `LoadFigureSpec`,
`DownloadOpenTopoDEM`) get `@toolbox_core.record_pyt_run(<cli-name>,
site_config_param=None)`, following the #403 / `validate-db` precedent for
tools with no site config. None has a geodatabase parameter, so
`_pyt_run_history_path` uses its documented cwd fallback. Recorded names match
the CLI subcommand names (`harvest`, `inspect`, `parser-profile`,
`figure-spec`, `download-dem`) so a tool's history is one series regardless of
which surface ran it.

The test that should have caught this was an exact-match allowlist of the 16
decorated tools — it froze a snapshot instead of asserting the rule, and
agreed with the five omissions. It is replaced by the invariant: *every* tool
class defining `execute()` carries the decorator, and every recorded name is a
live CLI subcommand.

### 4. CI coverage (#452)

Recorded as an amendment to **ADR-0110**, not duplicated here: `build.yml` is
deleted and the Sonar scan becomes the last step of the existing `ci.yml`
`pytest` job, reading the `coverage.xml` that job now produces. See ADR-0110's
2026-08-05 amendment for the alternatives and cost reasoning.

### 5. Optional-extra test gating (#441)

`requires_pyproj = pytest.mark.skipif(...)` applied to the 16 test functions
that transform, rather than a module-level `importorskip`, so the 15
parse/unit-scale tests that need no pyproj keep running on a bare install.

## Consequences

### Positive consequences

- Pull requests can pass the quality gate again, and coverage is measured
  instead of assumed — at *lower* CI cost than the two-workflow arrangement it
  replaces.
- Two QA channels that were structurally incapable of reporting anything now
  report. A Pro harvest where every attachment failed no longer looks identical
  to a clean one.
- Editing the shipped potentiometric spec now changes its output, and the
  "labels only" comment is true.
- Run history covers all 21 `.pyt` tools, so `evaluate-readiness` stops
  reporting "never run" for sites driven from Pro.
- Three new invariant tests replace point checks, so the *next* instance of
  each class fails in CI: every `.pyt` `execute()` is recorded; recorded names
  are live CLI commands; no `.pyt` tool declares a named parameter its body
  never reads.

### Negative consequences

- **#446 changes a shipped `.pyt` tool's parameter list.** Any saved
  geoprocessing model or script referencing `FullPipeline`'s `export_dir` by
  position or name must drop it. It was required-and-discarded, so no behavior
  depended on its value.
- **#443's `contours:` validation is a new failure mode.** A figure spec with a
  typo'd `method` now raises instead of quietly contouring with `TIN`. That is
  the intent, but it can surface in an existing spec that was previously inert.
- **#448 removes a public module-level function.** It was dead in-repo; an
  out-of-repo caller (there is none known) would need
  `config.load_flat_screening_levels`.
- **#445 changes which file wins for a site that set both.** The shipped H281
  pair carried identical values, so nothing moves there — but a site whose
  parser profile and site config disagreed now follows the site config. The
  filter also starts *working* for `init-site`-generated sites, which can
  surface out-of-range rows that previously imported clean. Any parser profile
  outside this repo still carrying the key becomes inert config; the new
  parametrized test catches that for shipped profiles only.
- **#431 makes failed attachments loud in Pro.** Runs that previously reported
  a plain count now show errors. That is the point, and it will make some
  existing runs look worse than they did.
- **#444 and #431 are arcpy-adjacent**; the `.pyt` decorator and call-site
  changes cannot be executed by the headless suite (ADR-0077 / `pragma: no
  cover`). They are pinned by ast-level and fake-arcpy tests, and the live-Pro
  leg remains owner QA.
- **#441's per-test marking is 16 decorators** rather than one module-level
  line — deliberately, to keep the pyproj-free tests running, at the cost of a
  decorator to maintain on each new transform test.

## Alternatives considered

- **Delete `generate_callouts: false` from the spec** instead of honoring it —
  rejected: that accepts the figure gets callouts, contradicting the spec's own
  comment and the CKG figure's purpose.
- **Honor `generate_callouts` at each `.pyt` call site** — rejected: two call
  sites today and a third whenever a tool is added; the guard belongs where all
  callers route.
- **Wire `FullPipeline`'s `export_dir` into an export step** — rejected: it
  would fold Tool 6's job into Tool 7 against the pipeline's stated design
  ("kept separate so layouts can be reviewed first").
- **Add an exclusion list to ADR-0068 naming the five undecorated tools** —
  the issue's other option. Rejected: no principle distinguishes them, their
  CLI counterparts are all recorded, and the exclusion would institutionalize
  the observability split.
- **Keep the recorder allowlist test and just add five entries** — rejected:
  it would pass today and go stale at the next tool, which is exactly how this
  shipped.
- **Lower or drop SonarCloud's coverage condition (#452 option B)** — see the
  ADR-0110 amendment; free and immediate, but unversioned, invisible in review,
  and it hides real regressions along with the false one.
- **Module-level `importorskip("pyproj")` for #441** — rejected: it would also
  skip 15 tests that have no pyproj dependency.
- **Let the parser profile own `plausible_gwe_range_ft` (#445's other option)**
  — the smaller code diff (drop it from `_SITE_MIN`, add it to the profile
  template), but it makes a site property configurable per workbook layout,
  discards the type-checking already in `config_validation`, and would need the
  site skeleton's documented behavior deleted rather than made true.

## Related decisions

- [ADR-0068: run-history recording](0068-pyt-run-history-recording.md) — the invariant #447 restores
- [ADR-0077: arcpy API-currency policy](0077-arcpy-api-currency-policy.md) — why the arcpy legs stay owner-QA
- [ADR-0110: CI + agent tooling batch](0110-ci-and-agent-tooling-batch.md) — amended by #452's fix
- ADR-0124 (PR #440) — the sibling silent-failure batch that filed these findings
