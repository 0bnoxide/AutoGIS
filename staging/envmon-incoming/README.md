# Environmental Monitoring Automation — ArcGIS Pro Toolbox

Converts irregular environmental monitoring Excel workbooks into a
normalized file geodatabase, QA reports, table-style analytical callout
feature classes, groundwater labels, DRAFT potentiometric contours, and
exported PDF/PNG figures — with full source-cell traceability and
idempotent imports.

## Requirements

* ArcGIS Pro **3.5.2+** (the spec header says 3.6; the body says 3.5.2 —
  the code targets 3.5+ APIs and uses nothing 3.6-specific).
* `openpyxl` — ships with the Pro conda environment.
* `PyYAML` — usually present; if not, clone the Pro env and
  `conda install pyyaml`. Every config loader also accepts **JSON** with
  the same structure as a fallback, so YAML is a convenience, not a hard
  dependency.
* 3D Analyst (TIN contours) and/or Spatial Analyst (IDW / Natural
  Neighbor). Missing licenses degrade to a skip **with a QA ERROR**, never
  a crash.

## Install

1. Copy this folder somewhere stable (the toolbox resolves `../src`
   relative to itself — keep the folder structure intact).
2. In ArcGIS Pro: Catalog pane → Toolboxes → **Add Toolbox** →
   `toolbox/EnvironmentalMonitoringTools.pyt`.

## First-run workflow (per site)

1. **Tool 1 – Inspect Environmental Workbook.** Read-only profile of every
   sheet: merged cells, header candidates, formula cells without cached
   values, suspected data start rows.
2. **Verify the parser profile.** `config/parser_profiles/
   H281_Glasgow_DataTables.yaml` is a **DRAFT built from the written spec
   only** — the real workbook was not available when it was authored.
   Compare every row/column anchor against the Tool 1 report, fix the
   `_TODO`s, then delete the DRAFT banner. Tool 9 can draft a profile for
   a brand-new workbook type.
3. **Tool 2 with mode `validate_only`.** Parse + QA without writing.
   Review `qa_output/import_qa_*.md`. Iterate until the errors are
   understood.
4. **Tool 2 with mode `append`.** Loads the GDB. Re-running is safe:
   unique-key rows are skipped (each skip logged, never silent). Use
   `replace_batch` / `replace_site_event` for corrections.
5. **Tool 3 → Tool 4.** Current-event wide table, then callout feature
   classes. Collisions are resolved automatically; anything still
   colliding is flagged `COLLISION_WARNING` — fix those via the
   placement-override table (`config/placement_overrides/
   README_overrides.md`) and re-run Tool 4.
6. **Tool 5 (optional).** DRAFT contours + DRAFT flow arrow. Everything is
   stamped `ReviewStatus = 'DRAFT'`; a qualified professional must review
   before these appear on a deliverable.
7. **Tool 6.** Copies the template APRX (never edits it), repaths to the
   GDB, applies definition queries / layout text / extent, runs pre-export
   QA (broken sources, empty required layers), exports. Existing files are
   never silently overwritten — exports are version-suffixed.
8. **Tool 7** chains 2→5 with QA gates, and deliberately stops before
   export so layouts can be reviewed; **Tool 8** validates cross-table
   integrity any time.

## Non-negotiable data rules (enforced in code)

* The source workbook is opened read-only and **never modified**.
* Nondetects are **never** coerced to 0 — `ResultNumeric` stays NULL and
  the reporting limit is preserved (`<1.0` renders as `<1.0`).
* `Dry` / `NM` / `NS` rows are excluded from contouring with an
  `ExclusionReason`, not deleted.
* Formula cells with no cached value are a QA **ERROR**, not a guess.
* Screening comparison is tri-state: detected results compare
  True/False; nondetects and statuses are NULL ("not evaluable").
* Nothing is dropped silently — every skip/ambiguity becomes a QA record
  (CSV + JSON + Markdown + `Env_ImportQA`).
* No regulatory number is invented: screening levels come from the
  workbook's screening row, else `config/screening_levels/` (shipped all
  null with `_TODO` source citations — populate before production).

## Layout / repo map

```
config/            all site-, workbook- and figure-specific settings (YAML)
src/               importable engine (pure-Python core + lazy-arcpy modules)
toolbox/           EnvironmentalMonitoringTools.pyt (10 tools)
templates/         place your .aprx / .lyrx / template .gdb here
tests/             pytest suite + synthetic workbook generator (56 tests)
qa_output/         QA reports land here
exports/           figure exports land here
```

## Testing

```
pip install pytest openpyxl pyyaml
python -m pytest tests
```

56 tests cover the result parser, date handling, the synthetic-workbook
end-to-end normalization (formula QA, exceedances, footnoted screening
levels, source-cell tracking, RPD recompute/mismatch), the
selection/duplicate/depth rule engine, callout table/geometry/collision,
and the assemble pipeline with overrides. **arcpy-dependent code
(cursor I/O, contouring, layouts, export) is not unit-testable outside
Pro and has not been executed here** — exercise Tools 1–8 on a copy of
real data before trusting outputs.

## Known limitations (read before relying on this)

1. **The H281 parser profile is unverified** (real workbook absent at
   build time). Tool 1 + human review is mandatory before the first
   import.
2. **Callout cartography matches CKG/ZT42 structurally** (box, gridlines,
   leaders, styled cell anchors with exceedance/nondetect flags). Exact
   visual parity needs `.lyrx` symbology tuned against the reference PDF
   figures, which were also not available; place tuned symbology in
   `templates/lyrx/` and reference it from the figure specs.
3. `average_parent_and_duplicate` averages only detect+detect pairs and
   flags every averaged value with a QA WARNING; averaging field
   duplicates is statistically dubious with nondetects and the rule
   exists only because the spec demands it.
4. Geometry inserts inherit each feature class's spatial reference; set
   the site `coordinate_system` and build the GDB in that SR before
   importing wells.
