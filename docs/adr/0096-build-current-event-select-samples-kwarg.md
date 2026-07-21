# ADR-0096: Fix BuildCurrentEvent/BuildCallouts select_samples kwarg drift + regression pin

**Status:** Accepted

**Date:** 2026-07-21

## Context

Live headless testing of the arcpy execute bodies (the `# pragma: no cover`
seams, in the `arcgispro-py3-autogis` clone — a prototype of issue #272's
Option 2) surfaced a shipped defect on `origin/main`:

`build_current_event.build_current_event_wide()` — the arcpy execute body behind
**Tool 3 (BuildCurrentEvent)** and, transitively, **Tool 4 (BuildCallouts)**
(`build_figure_dataset.generate_callout_features` calls it) — invoked the
arcpy-free helper `select_samples(...)` with `target_analyte_name=`, but the
parameter is named `target_analyte` (`build_current_event.py:57`). The keyword
is passed **unconditionally** (line 419), so the function raised
`TypeError: select_samples() got an unexpected keyword argument
'target_analyte_name'` on **every** invocation. Both LOCAL tools were broken in
the current release.

Root cause is the exact class issue #272 tracks: `select_samples` is unit-tested
and `build_current_event_wide` is not (it needs `arcpy_env()`), so a parameter
rename updated the callee and its tests but not the arcpy-only caller. The
headless dev suite (arcpy-free invariant, ADR-0002) structurally cannot reach
the call; ADR-0091's qualification runner does not execute tool bodies. The
green suite was false comfort — this is the same failure mode as #174/#214.

## Decision

1. **Fix:** `build_current_event.py:419` `target_analyte_name=` → `target_analyte=`.
   Confirmed live: `build_current_event_wide` now returns 5 wide rows against a
   seeded scratch GDB and persists `Env_CurrentEventWide`; `generate_callout_features`
   no longer raises (it correctly degrades to "needs well geometry").

2. **Regression pin (arcpy-free, per #272 Option 5 / ADR-0091's backport rule):**
   `test_build_current_event_wide_calls_select_samples_with_valid_kwargs` in
   `tests/envmon/test_build_current_event_rows.py`. It ast-parses
   `build_current_event_wide`'s source, extracts every `select_samples(...)` call
   site's keyword names, and asserts they are a subset of
   `inspect.signature(select_samples).parameters`. This catches caller/callee
   kwarg drift for this seam **without arcpy**, so it runs in the normal CI where
   the bug actually escaped. It fails on the pre-fix source and passes after.

## Consequences

- Tools 3 and 4 execute again; the pin guards the specific seam going forward.
- The pin is call-site-specific (one function, one callee). It is a targeted
  backport, not a general kwarg linter — the systemic coverage is issue #272's
  job (Options 1/4 catch this class more broadly: static stubs, mock-vs-real
  signature contract).
- **Sibling findings from the same campaign, tracked separately (not fixed here):**
  **F1** — `Env_AnalyticalResults.ScreeningLevelSource` is TEXT(64) but production
  `screening_levels.yaml` sources are 128–162 chars, so real imports fail the arcpy
  INSERT (`Field length exceeded`); needs a schema field-widen + migration ADR.
  **F3** — `build_analytical_key.write_analytical_key_gdb_table` writes to
  `Env_AnalyticalKey`, a table absent from `gdb_schema.py` (latent; likely unwired).

## Related

Issue #272 (automated arcpy testing — umbrella). ADR-0002 (arcpy-free invariant),
ADR-0077 (doc-verify), ADR-0091 (qualification runner + backport-pin rule).
