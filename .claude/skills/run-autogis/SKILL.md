---
name: run-autogis
description: Run, start, test, screenshot, or verify the AutoGIS CLI — launch commands, smoke-test headless tools, confirm changes work end-to-end.
---

AutoGIS is a Python CLI (`autogis`) with two surface areas: **headless** tools (no arcpy, openpyxl only — usable anywhere) and **LOCAL** tools (require ArcGIS Pro/arcpy). This skill covers the headless surface, which is what agents can drive without a Pro license.

Entry point: `autogis` (registered via `pyproject.toml` scripts). No build step needed; `pip install -e .` if the entry point is missing.

## Prerequisites

Python 3.10+, deps installed:

```
pip install -e .[dev]
```

No `apt-get` packages needed on Windows. On Linux: `pip install -e .` (no `[dev]` optional group required for smoke).

## Run (agent path)

All headless commands exit 0 on success, non-zero on error. Check exit code + stdout.

### Verify CLI is up

```
autogis --help
```

### Tool 10 — figure-spec (fastest smoke)

```
autogis envmon figure-spec autogis/config/figure_specs/CKG_GW_Analytical.yaml
```

Expected: `Figure spec 'CKG_GW_Analytical' loaded.`

### Tool 1 — validate-config

```
autogis envmon validate-config autogis/config/sites/H281_Glasgow.yaml \
  --profile autogis/config/parser_profiles/H281_Glasgow_DataTables.yaml
```

Expected: last line `Status: PASS` (warnings about `_TODO` placeholders are normal — those are DRAFT stubs).

### Screening levels inspect

```
autogis envmon manage-screening-levels \
  autogis/config/screening_levels/screening_levels.yaml --list
```

### Analyte dictionary check

```
autogis envmon manage-analyte-dict \
  autogis/config/analytes/analyte_dictionary.yaml --check
```

Warnings about `_TODO screening_level_source` are expected — those analytes are pre-production stubs.

### Full test suite

```
python -m pytest -q
```

Expected: 433+ passed, 0 errors. This is the definitive check — run it before claiming any change works.

## Run (human path)

Same commands — the CLI is the UI. No window opens.

## LOCAL tools (Tools 2–8)

Commands like `import-gdb`, `build-event`, `export-figures` guard on arcpy at runtime:

```
autogis envmon import-gdb --help   # shows usage
autogis envmon import-gdb ...      # errors cleanly without arcpy
```

These can only be driven end-to-end inside ArcGIS Pro via the `.pyt` toolbox at `autogis/adapters/toolbox.pyt`. The CLI path for them is intentionally just a guard+redirect.

## Gotchas

- `autogis envmon parser-profile` requires both `PROFILE` and `WORKBOOK` args — it's not a pure validator, it needs a real Excel file to parse against.
- `_TODO` warnings in validate-config output are expected; they're DRAFT sentinel values, not validation failures.
- `autogis harvest` requires `--config` pointing at a harvest config (see `autogis/config/inspection-job.example.yaml`). It also calls AGOL APIs — can't smoke-test headlessly without a live org.
- `autogis agol publish-layer` requires arcgis cloud SDK (`pip install arcgis`) and a live AGOL session — not testable headlessly.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `autogis: command not found` | `pip install -e .` from repo root |
| `ModuleNotFoundError: autogis` | Same — editable install not done |
| `No module named 'openpyxl'` | `pip install openpyxl` |
| Validate-config exits non-zero with `_TODO` | Normal — `_TODO` triggers warnings, not errors, unless `--fail-on warning` is passed |
