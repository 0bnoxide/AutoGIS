# Wire `export_summary_tables` into the CLI — design

**Date:** 2026-06-26
**Status:** Approved (brainstorming)
**Module under wire:** `autogis/core/envmon/export_summary_tables.py` (merged PR #18)

## Problem

`export_summary_tables()` is a complete, tested headless function (9 tests, PR #18)
that writes three **client-facing report-appendix** cross-tab sheets:

- **Current Event** — locations × analytes, latest sample date per location
- **GW by Event** — (location, analyte) × sorted event dates (stacked)
- **Soil by Depth** — (location, depth-interval) × analytes, SOIL matrix only

It has no CLI entry point. The only existing exporter command, `export-summary`,
is wired to a *different* module (`export_summary.py`) that produces flat QA
verification sheets (raw record dumps) — a distinct tool. We need a new command
for `export_summary_tables` that is clearly separated from `export-summary`.

## Decision: command name

`export-report-format-summary-tables` (CLI kebab-case, lowercase per click
convention). Chosen for maximum separation from the existing `export-summary`
command and to communicate the output's purpose (formatted report tables, not QA
sheets).

## Architecture

A new headless `click` command on the `envmon` group in
`autogis/adapters/cli.py`, placed alongside `export-summary` and
`evaluate-rpd-qa`. Pure core: read a CSV of `AnalyticalResultRecord`, call
`export_summary_tables()`, render QA. No arcpy, no `_guard`. Lazy imports inside
the function body, matching every other headless command in the file.

## Command signature

```
autogis envmon export-report-format-summary-tables
    --results-csv PATH   (required, exists=True)   CSV export of Env_AnalyticalResults
    --output PATH        (required)                output .xlsx path
    --site-id TEXT       (default "")              filter + label; auto-filled from
                                                   first record when blank
    --no-current-event   (flag, default off)       drop the "Current Event" sheet
    --no-gw-by-event     (flag, default off)       drop the "GW by Event" sheet
    --no-soil-by-depth   (flag, default off)       drop the "Soil by Depth" sheet
    --report PATH        (default None)            write QA report (.md/.json/.csv
                                                   by extension)
    --fail-on [error|warning]  (default error)
```

The `--no-*` flags use `is_flag=True, default=False` and are passed to the
function inverted: `include_current_event=not no_current_event`, etc.

## Data flow

1. `read_records_csv(Path(results_csv), AnalyticalResultRecord)` — the loader
   already used by `export-summary` and `evaluate-rpd-qa`
   (`autogis/core/envmon/evaluate_rpd_qa.py`).
2. If `--site-id` is blank and records exist, default it to `results[0].SiteID`
   (mirrors `export_summary_cmd`).
3. Build a fresh `QACollector()`, then call:
   ```python
   export_summary_tables(
       results, Path(output), site_id=site_id,
       include_current_event=not no_current_event,
       include_gw_by_event=not no_gw_by_event,
       include_soil_by_depth=not no_soil_by_depth,
       qa=qa)
   ```
4. `click.echo(f"Written: {out}")`, then hand `qa` to the existing
   `_render_qa(qa, report, fail_on)` helper for rendering + exit code.

## Error handling

- `export_summary_tables` emits only INFO/WARNING records (soil-absent,
  empty-sheet, export-complete). With default `--fail-on error` the command
  always exits 0; `--fail-on warning` surfaces those warnings as a non-zero exit
  via `_render_qa`'s existing `FAIL → SystemExit(1)` path.
- `--results-csv` uses `type=click.Path(exists=True)`, so a missing input file is
  a clean click error.

## Testing

New file `tests/test_cli_envmon_export_report_format.py` (matching the
`tests/test_cli_envmon.py` location and `CliRunner` style). A small helper writes
a results CSV from `AnalyticalResultRecord` instances via `csv.DictWriter` over
`dataclasses.asdict` (the inverse of `read_records_csv`, which ignores unknown
columns and coerces by type hint).

1. **Happy path:** write a results CSV with GW + SOIL records, invoke the
   command, assert `exit_code == 0` and the `.xlsx` exists with sheet names
   `{"Current Event", "GW by Event", "Soil by Depth"}`.
2. **Sheet toggle:** invoke with `--no-soil-by-depth`, assert the output
   workbook's sheet names exclude `"Soil by Depth"`.
3. **Warning escalation:** invoke GW-only data with `--fail-on warning`, assert
   non-zero exit (the soil-absent warning escalates to FAIL).
4. **Registration/help:** invoke `--help`, assert `exit_code == 0` and the
   `--results-csv` / `--output` / `--fail-on` options appear (mirrors the
   existing `test_import_edd_cmd_registered`).

All tests are arcpy-free and run under `python -m pytest -q`.

## Out of scope (YAGNI)

- No `--samples-csv`: `export_summary_tables` does not consume `SampleRecord`.
- No changes to `export_summary_tables.py` itself — it is complete and tested.
- No `.pyt` toolbox changes — this is a headless tool.
