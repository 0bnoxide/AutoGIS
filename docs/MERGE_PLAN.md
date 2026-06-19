# AutoGIS Suite Merge — Architecture & Handoff Plan

**Status:** plan / not yet implemented
**Audience:** Claude Code, working in this repo
**Goal:** Fold the Environmental Monitoring Automation toolbox into the AutoGIS
harness so the two become one CLI- and GUI-driven suite of tools, with each
tool pinned to a runtime (cloud / local / hybrid).

This document is the context bridge between two separately-built projects. It
was written after reading both trees in full. Treat the file inventories,
entry points, and signatures below as ground truth as of this writing, but
re-verify against the actual source before editing — do not trust this summary
over the code.

---

## 1. The two codebases, as they actually are

### A. AutoGIS harness (this repo, `main`, on GitHub)

Clean ports-and-adapters layout, pip-installed package, one tool today.

```
autogis/
  core/        download.py  gis_session.py  harvester.py  manifest.py
               models.py    state.py        templates.py
  adapters/    cli.py  config_loader.py
  config/      inspection-job.example.yaml
pyproject.toml   tests/   README.md
```

Key facts:

- **Dependencies:** `arcgis`, `PyYAML`, `click`. **No arcpy.** Talks to AGOL
  feature layers through the `arcgis` Python API, so it genuinely runs
  cloud-side (scheduled script / hosted notebook / server) as well as locally.
- **Entry point:** `pyproject.toml` `[project.scripts]` →
  `autogis-harvest = "autogis.adapters.cli:main"`. Single `click.command`.
- **Core is arcgis-injected and optional at import** (`harvester.py` guards
  `from arcgis.features import FeatureLayer` in try/except; tests inject the
  layer). This is the pattern to preserve.
- **Config:** `adapters/config_loader.load_config(path, overrides) ->
  (HarvestConfig, profile)`. `HarvestConfig` is a flat dataclass in
  `core/models.py`. YAML only.
- **Auth/session:** `core/gis_session.build_gis(profile|user/pass)` and
  `build_gis_from_env(profile)`. AGOL only (`https://www.arcgis.com`).
- **Result reporting:** `core/models.RunSummary` (downloaded/skipped/failed
  counters) + `core/manifest.Manifest` (CSV+JSON). CLI prints one summary line.
- **State:** `core/state.py` writes `.harvest_state.json` for incremental runs.

### B. Environmental Monitoring Automation (`staging/envmon-incoming/`)

Delivered as a v1.0.0 zip, **now staged into this repo** under
`staging/envmon-incoming/`. ArcGIS Pro `.pyt` toolbox, 10 tools, flat `src/`
on `sys.path`, **not a package**, no `pyproject.toml`.

```
staging/envmon-incoming/
  src/        23 modules (engine)
  toolbox/    EnvironmentalMonitoringTools.pyt   (10 Tool classes)
  config/     analytes/  figure_specs/  parser_profiles/
              placement_overrides/  screening_levels/  sites/
  tests/      conftest.py + 3 test modules (56 tests, synthetic workbook)
  templates/  (place .aprx/.lyrx/template .gdb here — currently empty)
  qa_output/ exports/   (output landing dirs)
  README.md  CHANGELOG.md
```

Key facts:

- **Requires ArcGIS Pro 3.5.2+ / arcpy** for its data-writing tools. `openpyxl`
  and `PyYAML` (with JSON fallback everywhere — see `envmon_config.load_config`).
- **Entry point:** the `.pyt` only. No CLI. The toolbox does
  `sys.path.insert(0, ../src)` then `from qa_checks import ...` etc. — flat,
  non-namespaced imports. **This must change on merge** (package + relative
  imports; drop the sys.path hack).
- **arcpy boundary is already clean.** 14 of 23 `src` modules have **no arcpy**
  reference at all: `result_parser`, `table_normalizer`, `normalize_*` (5),
  `callout_geometry`, `callout_collision`, `callout_templates`,
  `excel_workbook_inspector`, `excel_profile_reader`, `envmon_config`,
  `qa_checks`. arcpy appears only at the GDB/layout I/O edge
  (`import_to_gdb`, `build_figure_dataset`, `groundwater_contours`,
  `layout_manager`, `export_figures`, `gdb_schema`, `validate_database`,
  `build_current_event`) and is mostly **lazily imported inside functions**.
- **Config:** `src/envmon_config.py` is richer than the harness loader —
  typed dataclasses `SiteConfig`, `ParserProfile`, `FigureSpec` each with a
  `.load(path)` classmethod, a `ConfigError`, `load_config(path) -> dict`,
  and YAML-or-JSON loading. Plus `load_analyte_dictionary`,
  `load_screening_levels`.
- **QA / reporting:** `src/qa_checks.py` — `QARecord` (severity, category,
  message, full source-cell provenance) + `QACollector` with
  `write_csv/write_json/write_markdown` and `as_gdb_row` (writes to an
  `Env_ImportQA` table). `src/logging_utils.py` already mirrors logs to arcpy
  via an `_ArcpyHandler` (AddMessage/AddWarning/AddError). **This is the
  reporting substrate the merged suite should standardize on** — it is
  strictly richer than the harness's `RunSummary`.
- **The `.pyt` Tool classes are already thin shims:** each `execute()`
  marshals params → calls a `src` function → renders via `_msg(messages, qa)`.
  That validates the one-core/multi-adapter target; the GUI adapter pattern
  already exists in embryo.

Carried-over caveats from the build (still true, do not regress):

1. The H281 parser profile is a **DRAFT from spec, never verified against the
   real workbook**. Tool 1 + human review is mandatory before first import.
2. arcpy code paths are **untested outside Pro** — CI can only cover the
   pure-Python core.
3. `average_parent_and_duplicate` is statistically dubious with nondetects;
   implemented because the spec demanded it, flagged with a QA WARNING. Keep
   the flag.
4. Screening-levels file ships all-null with `_TODO` citations — populate
   before production.

---

## 2. Target architecture

One core, three adapters. Each tool declares a runtime capability; adapters and
a guard enforce it.

```
autogis/
  core/
    common/        config.py  qa.py  reporting.py  logging.py   # shared substrate
    harvest/       (existing harvester core, moved under here)
    envmon/        (the 24 src modules, repackaged, relative imports)
  runtime/
    capabilities.py    # Runtime enum: CLOUD | LOCAL | HYBRID; per-tool registry
    sessions.py        # session providers: AGOL-profile/env, Pro-active-portal, arcpy-env
  adapters/
    cli.py             # click GROUP: `autogis harvest …`, `autogis envmon import …`
    toolbox.pyt        # Esri .pyt wrapping the SAME core (GUI adapter)
  config/
pyproject.toml         # extras: cloud=["arcgis"]; arcpy runtime-detected, NOT an extra
```

Design rules:

- **Adapters are dumb.** A `.pyt` Tool class or a CLI subcommand only marshals
  inputs into a core config object, calls the core function, and renders the
  result. No business logic in either adapter. If logic leaks into `execute()`,
  GUI and CLI behavior fork — the exact drift that already bit this project.
- **`arcgis` and `arcpy` never both required to import the package.** Keep both
  lazy. `cloud` extra installs `arcgis`; `arcpy` is detected at runtime (it is
  not pip-installable — it ships with Pro). Importing any `core` module must
  succeed with neither installed (the harness already does this; preserve it
  when moving envmon modules).
- **Single validation source.** GUI validation (`.pyt updateMessages`) and CLI
  validation (YAML loader) must both construct and validate the *same* config
  dataclass. Put validation on the dataclass; do not duplicate per adapter.

---

## 3. The four reconciliations (the real work)

These are where the two projects disagree and a decision must be made. The
recommended resolution is given for each.

**3.1 Config systems.** Harness `load_config -> (HarvestConfig, profile)`,
flat dataclass, YAML-only. Envmon `envmon_config` — typed `.load()` dataclasses,
`ConfigError`, YAML+JSON. → **Adopt the envmon convention** (typed dataclasses
with `.load()` + `ConfigError` + JSON fallback) as `core/common/config.py`;
re-express `HarvestConfig` in that style. It is the more mature of the two.

**3.2 Reporting / QA.** Harness `RunSummary`+`Manifest` (print once). Envmon
`QACollector`/`QARecord` + `logging_utils._ArcpyHandler` (structured, severity,
provenance, multi-format writers, arcpy mirror). → **Standardize on
`QACollector` + the logging mirror** as `core/common/qa.py` + `logging.py`.
Fold harvester's counters in as a small summary view over QA records. This also
gives the GUI adapter its progress/message channel for free (the `_ArcpyHandler`
already does the arcpy mirroring; the CLI renders the same records to stdout).
Add a cancel-check hook so the `.pyt` can honor Pro's cancel button.

> **Forward requirements — build `core/common` to satisfy these now**, even
> though the features that need them ship later (see
> `docs/HARVESTER_ENHANCEMENTS.md`). Deferring four planned harvester features
> until after the merge is only cheap if the shared substrate anticipates them:
>
> 1. **Thread-safe reporter + cancel/progress hook.** `RunSummary.record` and
>    `Manifest.add` are not thread-safe today; the merged reporter must be safe
>    to call from worker threads so parallel downloads drop in without a rewrite.
> 2. **Manifest/result record reserves provenance fields.** Reserve columns for
>    `checksum` (+ algorithm), `geometry` (WKT/GeoJSON), and
>    `source_table` / `relationship_id`. Adding these after the fact means a
>    second manifest-schema migration (GeoJSON manifest, checksums/dedup, and
>    related-tables support all depend on them).
> 3. **One "seen-before" abstraction.** Model harvester's checksum-based skip
>    and envmon's unique-key idempotent import as a single concept in
>    `core/common`, not two parallel implementations.

**3.3 Packaging & imports.** Envmon is flat `src/` on `sys.path` with
non-namespaced imports (`from qa_checks import …`). → **Repackage into
`autogis/core/envmon/` with relative imports**, delete the `sys.path.insert`
in the `.pyt`, and pip-install the package into a cloned `arcgispro-py3` conda
env so the toolbox imports `autogis` like any library. Every
`from <module> import` in the 24 modules and the `.pyt` gets rewritten — this
is mechanical but touches every file; do it as one reviewable commit.

**3.4 Session/auth.** Harness builds an AGOL `GIS` from profile/env. Envmon
tools need an arcpy/Pro environment, and when run *inside* Pro the arcgis-API
tools can ride the signed-in portal instead of asking for credentials. →
**`runtime/sessions.py` exposes three providers:** AGOL-profile/env (CLI cloud),
active-Pro-portal (`GIS("pro")`, GUI), and arcpy-env (local geoprocessing).
Provider is selected by the tool's runtime flag + execution context.

---

## 4. Per-tool runtime classification

The capability flag earns its keep — the spread is real.

| Tool | Source | Runtime | Why |
|---|---|---|---|
| Attachment Harvester | `core/harvest` | **HYBRID** | `arcgis` API; runs cloud or local |
| 1. Inspect Workbook | `excel_workbook_inspector` | **CLOUD-OK** | openpyxl only, no arcpy |
| 9. Parser Profile Draft | `excel_workbook_inspector` | **CLOUD-OK** | openpyxl only |
| 10. Figure Spec Template | inline | **CLOUD-OK** | pure python file write |
| 2. Import to GDB | `import_to_gdb` | **LOCAL** | file-GDB cursors (arcpy) |
| 3. Build Current Event | `build_current_event` | **LOCAL** | rule logic pure, but GDB I/O is arcpy |
| 4. Build Callouts | `build_figure_dataset` | **LOCAL** | geometry inserts (arcpy) |
| 5. GW Contours | `groundwater_contours` | **LOCAL** | 3D/Spatial Analyst |
| 6. Export Figures | `export_figures`,`layout_manager` | **LOCAL** | `arcpy.mp` layouts/PDF — no cloud equivalent |
| 7. Full Pipeline | orchestrator | **LOCAL** | chains local stages |
| 8. Validate Database | `validate_database` | **LOCAL** | GDB cursors |

Note the genuinely portable seam: Tool 3's selection/depth/duplicate rules and
all `normalize_*` logic are pure-Python and could later target hosted feature
layers instead of a file GDB — a future cloud port, **out of scope for this
merge**. Do not attempt it now; just keep those modules arcpy-free so the door
stays open.

The `.pyt` GUI adapter exposes every LOCAL and HYBRID and CLOUD-OK tool (it runs
inside Pro, where everything is available). The CLI exposes all tools but the
runtime guard refuses a LOCAL tool when arcpy is absent, with a clear message.

---

## 5. Staged implementation plan (suggested commit order)

Each step is a reviewable commit on a feature branch (e.g. `merge/envmon-suite`).
Keep `main` green throughout.

1. **Scaffold without behavior change.** Add `core/common/`, `runtime/`, and the
   `Runtime` enum + tool registry. Move existing harvester modules under
   `core/harvest/` with re-exports so nothing breaks. Convert
   `[project.scripts]` to a `click` group `autogis` with `harvest` as the first
   subcommand. Tests still pass unchanged.
2. **Reporter interface.** Introduce `core/common/reporting.py` (events +
   cancel hook) over `QACollector`; wire CLI rendering. Harvester emits through
   it. No envmon code yet.
3. **Reference GUI adapter.** Write a `toolbox.pyt` with **one** Tool class
   wrapping the existing harvester, importing the installed package (no
   sys.path). This is the pattern every envmon tool will follow. Document the
   Pro install (clone `arcgispro-py3`, `pip install -e .`) and the toolbox
   cache/reload gotcha.
4. **Repackage envmon core.** Move the 23 `staging/envmon-incoming/src/*`
   modules → `core/envmon/`, rewrite imports to relative, fold
   `qa_checks`/`logging_utils`
   into `core/common`, reconcile `envmon_config` into `core/common/config.py`.
   Port the 56 tests. Pure-Python modules must import and pass with no arcpy.
5. **Wire envmon adapters.** Add envmon subcommands to the CLI group and the
   remaining 9 Tool classes to `toolbox.pyt`, all over the shared core. Apply
   the runtime guard.
6. **Cleanup.** Delete `staging/envmon-incoming/`. Update README to describe the
   suite, install paths (cloud vs Pro), and the runtime matrix. Update CHANGELOG.

Verification gate at each step: `pytest` green for arcpy-free code; arcpy paths
exercised manually on a copy of real data inside Pro before trusting outputs
(they remain un-CI-able).

---

## 6. Decisions (final — do not re-litigate)

Both previously-open questions are resolved. Build to these.

- **Repo shape: MONOREPO.** One `autogis` package with `core/harvest` +
  `core/envmon` sharing `core/common`. No second package. The arcpy-weight
  concern is handled by lazy imports + the `cloud` extra — a cloud target runs
  `pip install autogis[cloud]` and never imports the local modules; a Pro
  target runs `pip install -e .` in a cloned `arcgispro-py3` env. Splitting into
  `autogis-core` + `autogis-envmon` is explicitly rejected (versioning/publish
  coordination cost, and it would duplicate or fragment `core/common`).
- **CLI surface: register all, support three headless.** Every tool is
  registered in the `autogis` click group for a consistent
  `autogis envmon <tool>` namespace. Only the three pure-Python tools —
  **1 Inspect, 9 Parser Profile Draft, 10 Figure Spec Template** — are
  first-class headless/cloud-supported and documented as such. Tools **2–8 are
  registered but runtime-guarded**: they error clearly when arcpy is absent, and
  the `.pyt` GUI is their primary interface. Do not invest in rich CLI ergonomics
  (progress bars, fancy prompts) for 2–8 — the guard message and the `.pyt` are
  enough.

---

## 7. Quick-reference: signatures Claude Code will touch first

- `autogis/adapters/cli.py::run(config_path, where, out, incremental, *, gis_builder, harvest_fn, load_fn)` — already DI-shaped; generalize to a group.
- `autogis/adapters/config_loader.py::load_config(path, overrides) -> (HarvestConfig, profile)`
- `autogis/core/gis_session.py::build_gis_from_env(profile, gis_factory=GIS)`
- `staging/envmon-incoming/src/import_to_gdb.py::run_import(workbook, gdb, site_config, profile, analyte_dictionary_path, screening_levels_path, qa_output_dir, mode, matrix_filter, batch_id_to_replace, event_date, operator, allow_duplicate_records, allow_errors_override) -> dict`
- `staging/envmon-incoming/src/qa_checks.py::QACollector` / `QARecord`
- `staging/envmon-incoming/src/envmon_config.py::{SiteConfig,ParserProfile,FigureSpec}.load(path)`
- `staging/envmon-incoming/toolbox/EnvironmentalMonitoringTools.pyt` — 10 Tool classes, already thin; reuse as the GUI adapter template.
