# Preparation Brief — the last 4 "Planned" roadmap tools

**Date:** 2026-07-03
**Prepared by:** main session + 4 parallel `graph-codebase-navigator` research
dispatches (read-only, one per tool)
**Audience:** whichever coding agent implements each tool next

---

## Why this brief exists

README's "Planned — spec and/or implementation plan written, not yet coded"
section lists 4 remaining tools, each with a spec and/or plan doc written
2026-06-28. **All four docs have drifted from the current codebase** in ways
that would break a coding agent following them verbatim — stale function
names, architecture that predates ADR-0039, a spec that's literally
unbuildable (module-name collision), and in one case a plan that describes a
different tool than the roadmap actually asks for. Four independent
`graph-codebase-navigator` research passes verified each tool against live
code before any implementation starts. This doc is the reconciled result.

**One cross-cutting gotcha every single brief independently surfaced:**
`tests/test_capabilities.py::test_every_envmon_command_registered_for_discovery`
CI-fails if a new `@envmon.command` doesn't get a `_REGISTRY_SEED` entry in
`autogis/runtime/capabilities.py`. All four stale docs omit this. **Every
tool below needs a `_REGISTRY_SEED` tuple — treat it as non-optional.**

**Build order (independent tools, no cross-dependencies — build in any
order; suggested by ascending risk/size):**
1. CreateSurvey123SamplingEvent (2.7) — smallest, cleanest, plan is TDD-ready
2. GenerateWellInspectionPhotoReport (7.4) — needs a new dependency decision (resolved below)
3. GenerateSiteMapSeries (5.6) — largest reuse win, but touches `.pyt`-adjacent arcpy export
4. BatchEDDImport — **scope changed by user decision, see below: fold into Tool 2.2, not a new tool**

Follow the established batch pattern from the prior 4-tool batch
(`docs/superpowers/specs/2026-07-02-remaining-roadmap-items-brief.md`, PRs
#131-134): **one tool per agent, own branch/worktree/PR, merged and verified
before the next starts.** All four tools touch the same hotspots
(`capabilities.py`, `cli.py`, `README.md`) — parallel dispatch would collide
and risks an ADR-number race (see the 0034 collision in
`docs/adr/README.md` history). Sequential only.

---

## 1. CreateSurvey123SamplingEvent (Tool 2.7, headless/CLOUD)

**Docs:** spec `docs/superpowers/specs/2026-06-28-create-survey123-sampling-event-design.md`,
plan `docs/superpowers/plans/2026-06-28-create-survey123-sampling-event.md`

**Resolution: build from the plan, not the spec.** The plan is newer,
TDD-complete (ready-to-paste code for all 3 tasks), and — decisively — its
SampleID format (`{WellID}-{YYYYMMDD}-{Matrix}`) matches the live Survey123
form builder's calculation exactly
(`survey123_form_builder.py:98-101`, `concat(${WellID}, "-",
format-date(${SamplingDate}, "%Y%m%d"), "-", ${Matrix})`). The **spec's**
format (`{site_id}-{location_no_dashes}-{YYYYMMDD}-{matrix}`, e.g.
`H281-MW01-...`) would silently break reconciliation with Tool 2.6. Do not
use the spec's `build_sample_id()`.

**Verified against live code:**
- `SiteConfig.load()`, `load_analyte_dictionary()`, `load_config()` all exist
  in `autogis/core/common/config.py` with signatures matching the plan's
  usage.
- `survey123_form_builder.build_xlsform()` really does consume
  `event_config["analyte_groups"]` as `{group_name: [analyte_names]}` — the
  plan's "do not enrich this key" constraint is real and load-bearing.
- No new dependency: openpyxl only, already required.

**Corrections needed before implementing the plan verbatim:**
1. **Blocking:** plan never touches `capabilities.py` — add a
   `_REGISTRY_SEED` tuple, e.g.
   `("create-sampling-event", "CreateSurvey123SamplingEvent", "2.7", "CLOUD", "stable", "field", "Generate a pre-field sampling event plan workbook (expected samples, crew, COC draft)")`.
   No `TOOLS` dict entry needed (headless, no `_guard()` call) — optional
   symmetry only.
2. **Scope note (accepted cut, not a blocker):** the plan drops the
   Approved spec's `QACollector`/`--report` output and `--coc-template`
   support. Reasonable v1 YAGNI cut — document it in the PR description
   rather than silently diverging from an "Approved" spec.
3. Naming: this is distinct from the already-shipped `create-sampling-plan`
   / `CreateSamplingPlan` (roadmap 7.2, GIS-backed, different tool) — don't
   conflate.

**File map:** create `autogis/core/envmon/create_sampling_event.py` +
`sampling_event_writer.py`; modify `autogis/adapters/cli.py` (insert after
`build_survey_form_cmd`, which ends at line ~1602, before
`build-fieldmaps` at ~1605) and `autogis/runtime/capabilities.py`
(`_REGISTRY_SEED`); create 3 test files per the plan's Task 1-3 structure.

---

## 2. GenerateWellInspectionPhotoReport (Tool 7.4, headless/CLOUD)

**Docs:** spec `docs/superpowers/specs/2026-06-28-generate-well-inspection-photo-report-design.md`,
plan `docs/superpowers/plans/2026-06-28-generate-well-inspection-photo-report.md`

**Resolution: hybrid — plan's inputs + spec's XLSX output. User has
confirmed declaring Pillow as a dependency (see decision below); no fpdf2,
no HTML/PDF path.**

**Two hard blockers found in the spec, either of which rules it out as
written:**
1. **Module-name collision — the spec is literally unbuildable.**
   `core/envmon/well_inspection_report.py` **already exists** (shipped, PR
   #102, backs the `well-inspection-report` command) and its own docstring
   says photo attachments are explicitly out of scope, deferred to this
   tool. The spec proposes creating a file with that exact same name.
   **Use a different module name:** `well_inspection_photo_report.py`.
2. **"Zero new dependencies" is false.** openpyxl's `Image` embedding
   requires Pillow (`from PIL import Image`, raises `ImportError` without
   it) — Pillow is not declared in `pyproject.toml` and currently only
   works by luck of the environment having it installed.

**What to take from the plan:** source photos from the existing attachment
harvester's `manifest.csv` instead of requiring the user to hand-build a
redundant photo-manifest CSV. Verified: `AttachmentResult.saved_path`
(`core/harvest/models.py:19`) really does follow
`{harvest_dir}/{group}/{filename}` (`harvester.py:63-66`), and `group` is
guaranteed a single path component (sanitized, no separators) —
**but `group` is only the well_id if the site's harvest config's
`group_template` renders one.** This is a real, load-bearing pilot
assumption — isolate it in one function (`match_photos_to_wells`) and emit
a QA WARNING when a well has an inspection record but zero matched photos
(or vice versa). Reuse `index_field_attachments.load_manifest()`
(`core/envmon/index_field_attachments.py:37-44`) to read the manifest
rather than hand-rolling CSV parsing.

**What to take from the spec:** XLSX output via `openpyxl.drawing.image` +
`ws.add_image()` (no existing embed-image precedent in the codebase — this
part is genuinely new either way), one row/section per well: well ID +
condition, photo, GPS, inspection info, notes. GPS **must** come from the
user's inspection CSV — the harvest manifest's `geometry` column is
reserved/always-empty (`models.py:26-29`), so the plan's harvest-only
approach silently loses GPS. Keep GPS as an optional pair of columns.

**Drop entirely (YAGNI, confirmed by user's dependency decision):**
fpdf2, the HTML renderer, the `--pdf` flag. No other reporting tool in this
codebase auto-generates PDF; it's a manual downstream step everywhere else
(see ADR-0042 for `gen-boring-logs`'s explicit precedent of the same call).

**Dependency decision (user-confirmed):** declare `Pillow>=9.0` in
`pyproject.toml` (base deps or a `[project.optional-dependencies] report =
[...]` extra — implementer's call), lazy-imported inside the write function
so `core/` stays importable without it.

**Inspection CSV schema** — align with the *already-shipped*
`well_inspection_report.py`'s maintenance-log CSV headers
(`WellID, InspectionDate, Inspector, Condition, Notes`) plus add optional
`GPS_Lat, GPS_Lon` and `DepthToWaterFt`, so one CSV can eventually feed both
tools rather than inventing a third schema.

**File map:** create `autogis/core/envmon/well_inspection_photo_report.py`
+ `tests/envmon/test_well_inspection_photo_report.py` (Pillow-gated tests
use `pytest.importorskip("PIL")`); modify `autogis/adapters/cli.py` (new
`generate-inspection-report` command, anchor after `gen-boring-logs` block
~line 2328-2360), `autogis/runtime/capabilities.py` (`TOOLS["generate-inspection-report"]
= Runtime.CLOUD` + `_REGISTRY_SEED`), `pyproject.toml` (Pillow), `README.md`
(move 7.4 out of Planned into the shipped tables).

**Open risk to flag in the PR, not necessarily resolve:** per CLAUDE.md's
pre-production-stub convention, consider whether this needs a DRAFT banner
until validated against real field inspection photos.

---

## 3. GenerateSiteMapSeries (Tool 5.6, LOCAL/arcpy)

**Docs:** spec `docs/superpowers/specs/2026-06-28-generate-site-map-series-design.md`,
plan `docs/superpowers/plans/2026-06-28-generate-site-map-series.md`

**Resolution: build the spec's tool. Discard the plan's design outright —
it describes a different tool that misreads what 5.6 is.**

The roadmap's own definition (`docs/envmon-feature-roadmap.md:728-746`) is
unambiguous: "Builds figure packets across many sites/events," inputs are
"site list, event list, figure spec folder, output folder." That's the
spec's site × event × figure-spec matrix (`plan_map_series()`). The plan
instead built around ArcGIS Pro's Map Series / Data Driven Pages layout
feature (`arcpy.mp.MapSeries`) — which iterates pages *within one layout*
and structurally cannot span multiple sites or events, and which appears
**nowhere else in this codebase** (the plan invented a dependency on a
feature this project has never touched). **Mark
`docs/superpowers/plans/2026-06-28-generate-site-map-series.md` as
superseded** in its own header when you touch this — so it doesn't get
resurrected later.

**Architecture: CLI-first per ADR-0039, not the spec's `.pyt` toolbox
class.** The spec cites the now-refined ADR-0006 pattern (new `.pyt` tool
class). ADR-0039 supersedes that for generation-2 LOCAL tools with no
existing `.pyt` entry; its only trigger for adding a `.pyt` GUI is a need
for interactive map context, which a batch matrix exporter is the opposite
of. Exact precedent: `update-layout-text` (5.8, shipped this batch) reuses
`layout_manager.update_layout_text` — the same function the `.pyt`
figure-export pipeline calls — as a **plain CLI command**, not a `.pyt`
class. Apply the same reasoning to 5.6.

**Big reuse win — the arcpy export half is nearly already built.** Point
the implementer at `toolbox.pyt::ExportFigures.execute()` (lines ~439-525)
as the literal per-job template to replicate as a CLI loop:
1. `layout_manager.update_aprx_data_sources(aprx, gdb, qa)`
2. `layout_manager.apply_figure_definition_queries(...)` — this is the
   spec's "applies the figure spec's definition queries"
3. `export_figures.export_layouts(...)` — already supports `layout_names`
   filtering, multiple formats, and `combine_pdf` (covers the
   per-site/per-map-type/combined-appendix modes from the roadmap examples)
4. `export_figures.register_exports(...)` — writes the figure-registry
   manifest rows

**The only genuinely new code is the arcpy-free planner**
(`map_series_plan.py::plan_map_series()` — matrix expansion + deterministic
output naming, per the spec's Public API). Follow the dual-path guard
pattern from `survey-to-well-elevation` (`cli.py:2451-2517`), not the
unconditional guard used by 5.8: let `plan_map_series()` run under
`--dry-run` with zero arcpy, call `_guard("gen-map-series")` only right
before the export loop.

**Command name:** use `gen-map-series` (the spec's name, matches the
`gen-boring-logs` naming precedent) — not the plan's `generate-map-series`.

**File map:** create `autogis/core/envmon/map_series_plan.py` +
`tests/envmon/test_map_series_plan.py`; modify `autogis/adapters/cli.py`
(new `gen-map-series` command, anchor after `update-layout-text` ~line
2631), `autogis/runtime/capabilities.py` (`TOOLS["gen-map-series"] =
Runtime.LOCAL` **and** a `_REGISTRY_SEED` tuple — both surfaces, this is
the drift class ADR-0039/H3 already flagged), `tests/envmon/test_cli_guards.py`
(extend for the guard-error path), `README.md`. **Do not create**
`map_series.py`, `MapSeriesConfig`, or a `.pyt` tool class.

**Confirm before building:** how the on-disk "figure spec folder" input
resolves into the spec identifiers `export_layouts`/`LoadFigureSpec`
already expect — check `toolbox.pyt`'s figure-spec loading (~line 196)
against whatever `plan_map_series()` ends up taking as its `figure_specs`
parameter.

---

## 4. BatchEDDImport — **scope changed: fold into `batch-import-workbooks`, not a new tool**

**Doc:** plan only, `docs/superpowers/plans/2026-06-28-batch-edd-import.md`
(no separate design spec existed)

**User decision (2026-07-03): do not build a new tool.** The navigator
found that Tool 2.2, `batch-import-workbooks`
(`core/envmon/batch_workbook_importer.py`, CLI `batch-import-workbooks` at
`cli.py:3403-3463`), **already does headless batch EDD import today** —
composing `read_edd_file()` + `normalize_edd_rows()` per file, catching
per-file failures into a manifest without aborting the batch, aggregating
into `sample_records.csv`/`result_records.csv`. The only functional gap is
input shape: Tool 2.2 takes a manifest CSV enumerating
`(workbook_path, profile_path, site_id)` per row; the roadmap wants a
directory-glob with one shared profile/site. **Add that as an alternate
input mode on the existing command rather than building a second,
near-duplicate importer.**

**The original plan is also independently stale**, for the record (moot
now that scope changed, but relevant if anyone re-reads it): its central
reused function `run_edd_import_csv` **does not exist and never did** —
real functions are `read_edd_file()` + `normalize_edd_rows()` in
`edd_importer.py`. Its stated dependency,
`docs/superpowers/plans/2026-06-28-fix-import-edd-headless.md`, is also
unimplemented and references a nonexistent `parse_edd()`. Neither should be
followed as written even in the old scope.

**What to actually build:**
- Extend `batch_workbook_importer.py`'s `run_batch_import()` (or add a
  thin wrapper that synthesizes manifest rows from a directory glob +
  shared profile/site, then calls the existing function) to accept an
  alternate input mode.
- Extend the `batch-import-workbooks` CLI command
  (`cli.py:3403-3463`) with `--edd-dir` / `--profile` / `--site` /
  `--pattern` options as an alternative to the existing manifest-CSV input
  (mutually exclusive — pick one input mode per invocation).
- **No new `_REGISTRY_SEED` entry needed** — `batch-import-workbooks` is
  already registered. Just verify existing tests still pass after the
  signature/CLI extension.
- **No new module, no new command name.** This eliminates the plan's
  proposed `batch_edd.py`, `BatchImportSummary` dataclass, and
  `batch-import-edd` command entirely — the existing
  `BatchWorkbookImportSummary`-shaped result type (check its real name in
  `batch_workbook_importer.py`) already covers this.

**Open item to settle during implementation, not blocking:** confirm
whether `screening_levels`/`analyte_dictionary` config loading in the
existing command uses `load_screening_levels()`/`load_analyte_dictionary()`
(which unwrap a top-level key) vs. raw `yaml.safe_load()` — the navigator
flagged this as an existing, inherited risk in `batch_workbook_importer.py`
regardless of this change; worth a quick sanity check against a real
screening-levels YAML while you're in that code.

---

## Registration checklist (apply per tool, except #4 which needs none)

- [ ] `@envmon.command(...)` added to `autogis/adapters/cli.py`
- [ ] `_REGISTRY_SEED` tuple in `autogis/runtime/capabilities.py`
      (**CI-enforced**, `tests/test_capabilities.py::test_every_envmon_command_registered_for_discovery`)
- [ ] `TOOLS` dict entry in `capabilities.py` — only required if the command
      calls `_guard(...)`; optional-but-conventional for headless/CLOUD tools
- [ ] `README.md` tracker row moved from Planned to the appropriate shipped
      table; test count and module count updated (derive live, don't
      hardcode: `python -m pytest --collect-only -q`)
- [ ] ADR added (`docs/adr/NNNN-*.md`) — **check every open PR's files for
      the next-free number, not just `ls docs/adr/`** (the ADR-0034
      collision precedent, `docs/adr/README.md` history / PR #127)
