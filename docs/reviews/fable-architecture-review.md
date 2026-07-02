# AutoGIS architecture review — 2026-07-01

**Reviewer:** independent fresh-eyes pass (Fable 5, graph-backed via codebase-memory-mcp).
**Scope:** boundary design (core/adapters/runtime), the envmon module family,
the CLI/.pyt seam, and the config/QA layer. Not a bug hunt, not a style pass.
**Evidence basis:** graph queries (index: 5,654 nodes / 16,869 edges, status
ready at review time), targeted file reads, and a three-way registry diff.
Test baseline at review start: `python -m pytest -q` → **1082 passed**.

## Verdict in one paragraph

The load-bearing decisions are sound and holding: the arcpy-free import
invariant is intact across all ~250 Python modules, `QACollector` has genuinely
converged as the QA spine (65/85 envmon modules), and
`gdb_schema.AnalyticalResultRecord` is a real shared hub, not accidental
coupling. The debt is exactly where the maintainer suspected: **seams and
registries that each autonomous batch had to *remember* to update, and
didn't.** The CLI/.pyt contract has silently bifurcated into two generations
with opposite conventions; three hand-maintained registration surfaces have
drifted apart; ADR-0017's run-history contract was never wired on the write
side; and shared-helper adoption decays with each batch. None of this is yet
expensive to fix. All of it gets more expensive per batch.

---

## HIGH

### H1. ADR-0017's run-history write side was never implemented — readers consume a log nothing produces

ADR-0017 (`docs/adr/0017-run-history-csv-log.md`) says *"Every AutoGIS tool
execution needs an auditable record"* and names three consumers:
`EvaluateReportReadiness`, the dashboard mart, and the job queue.

Reality (graph + grep confirmed):

- `RunHistory.write` (`autogis/core/common/run_history.py:88`) has **zero
  production callers**. No CLI command, no `.pyt` `execute()`, no core module
  writes a `RunRecord`.
- Readers exist and are shipped: `envmon evaluate-readiness`
  (`autogis/adapters/cli.py:349-377`), `envmon run-history`
  (`cli.py:1020-1048`). They will forever see an empty/absent log unless the
  user hand-authors `run_history.csv`.
- `job_queue.py` and `dashboard_data_mart.py` — the other two consumers ADR-0017
  names — do not reference `RunHistory` at all.
- `source_registry.py:4` *mimics* the "append-only RunHistory pattern" but for
  a different log; it does not populate run history.

**Impact:** `evaluate-readiness` is a shipped tool whose core input is
structurally unpopulated. This is the largest gap between documented
architecture and code found in this review.

**Recommendation:** wire the write side once, at the adapter layer — a single
helper (or click result-callback) in `cli.py` that wraps command execution and
appends a `RunRecord` (best-effort, per the ADR), plus the same call in the
`.pyt` `execute()` bodies. Do *not* add per-module writes in core; that would
be 80 call sites for what one adapter hook can do. If the feature is instead
deferred, mark ADR-0017 as such so the readiness tool's status is honest.

### H2. The CLI/.pyt seam has bifurcated into two contradictory generations

ADR-0006 (`.pyt` as primary UI): tools 2–8 CLI commands guard then
**unconditionally redirect** to the `.pyt` — they never execute, even inside
Pro (`cli.py:1128-1305`). The `.pyt` (`autogis/adapters/toolbox.pyt:57-73`)
carries exactly these 13 tools (harvest, 1, 9, 10, 2–8, reconcile).

Every LOCAL tool added since (≈12 of them) follows the **opposite**
convention: guard, then execute the real work in the CLI via lazy arcpy — and
has **no `.pyt` tool at all**: `import-edd` (`cli.py:1329`),
`import-rtk-survey` (`cli.py:1477`), `route-survey123` (`cli.py:1788`),
`build-dashboard-data-mart` (`cli.py:2222`), `register-drone-flight`
(`cli.py:1537`), `import-drone-products` (`cli.py:1579`), `import-boring-logs`
(`cli.py:1643`), `survey-to-well-elevation` (`cli.py:1665`), `upgrade-schema`
(`cli.py:1378`), `export-snapshot` (`cli.py:1390`).

Consequences:

1. The guard's user-facing advice — *"Run it in the .pyt toolbox inside Pro"*
   (`autogis/adapters/guard.py:29-30`) — is wrong for every generation-2 tool:
   there is no toolbox entry to run. The correct advice for these is "run this
   CLI inside the arcgispro-py3 env".
2. **Two tools are unreachable in every environment.** `optimize-callouts`
   (`cli.py:1166-1175`) and the four `manage-callout-overrides` subcommands
   (`cli.py:1188+`) guard and then redirect to `.pyt` tools
   (`OptimizeCalloutPlacement`, `ManageCalloutPlacementOverrides`) **that do
   not exist** in `toolbox.pyt`. Inside Pro, the CLI still refuses; in the
   toolbox, the tool isn't there. (The core logic behind 5.3,
   `manage_callout_overrides.load_overrides`, *is* reachable indirectly via
   `build_figure_dataset.py:27`.)
3. Two redirect messages named the wrong (or nonexistent) `.pyt` class even
   for generation-1 tools — fixed in this review (see "Fixes made" below).

**Recommendation:** record a short ADR that supersedes/refines ADR-0006:
generation-2 LOCAL tools are **CLI-first inside the Pro conda env**, and a
`.pyt` GUI is added only when a tool needs interactive map context. Update
`guard.py`'s message to branch on whether the tool has a `.pyt` entry (one
boolean in the registry would carry this). Then either implement `.pyt` tools
for 5.2/5.3 or convert their CLI stubs into working commands — today they are
dead ends with tests asserting the dead end.

### H3. Three hand-maintained registration surfaces, no consistency test — and they have already drifted

A tool exists in up to four places: the click command (`cli.py`), the guard
registry (`capabilities.TOOLS`, 52 entries), the discovery registry
(`capabilities._REGISTRY_SEED`, 72 entries), and optionally the `.pyt`. All
are updated by hand; nothing checks agreement. Measured drift at review time
(78 click commands):

- **7 CLI commands invisible to `envmon list-tools`** — the discovery command
  whose entire purpose is completeness: `batch-import-workbooks`,
  `create-sampling-plan`, `draft-parser-profile`, `generate-arcade-labels`,
  `generate-event-changelog`, `migrate-legacy-data`, `reconcile-field-lab`.
  Five of the seven are the two most recent feature batches: the drift rate is
  roughly "every batch forgets".
- The guard side is currently consistent (all guarded names resolve; all
  TOOLS-LOCAL commands guard), but the prior `KeyError` incident (issue #62)
  was exactly this failure class, and `test_capabilities.py` asserts only 3
  hardcoded names.

**Recommendation:** one small test that introspects the `envmon` click group:
(a) every command name appears in `_REGISTRY_SEED` (or an explicit exemption
list), (b) every name passed to `_guard` is in `TOOLS`, (c) every
`_REGISTRY_SEED` command exists as a click command/group. ~25 lines; turns a
per-batch memory obligation into CI. Secondary: `ToolEntry`
(`autogis/core/envmon/tool_registry.py:17-25`) is a field-for-field copy of
`ToolCapability` (`autogis/runtime/capabilities.py:88-97`) — reuse the
dataclass and delete the copy.

---

## MEDIUM

### M1. Three competing arcpy-access styles inside core/envmon

The import invariant holds (verified: full package walk imports clean with
`arcpy`/`arcgis` absent — now enforced by `tests/test_boundary_imports.py`),
but *how* modules reach arcpy has drifted into three styles:

- **A — module-scope lazy provider** (8 modules):
  `from ...runtime.sessions import arcpy_env as _arcpy` at top level —
  `build_figure_dataset.py:46`, `export_figures.py:26`,
  `groundwater_contours.py:28`, `import_to_gdb.py:42`, `layout_manager.py:23`,
  `manage_callout_overrides.py:13`, `validate_database.py:28`, and
  `build_current_event.py:354` (module-scope import placed 354 lines into the
  file — legal, deliberate section marker, still a landmine for readers).
- **B — function-scope provider**: `import_boring_logs.py:175`,
  `register_drone_flight.py:107`, `survey_to_well_elevation.py:135`,
  `import_drone_products.py:171`, …
- **C — raw `import arcpy` in-function, bypassing the provider**:
  `build_analytical_key.py:210`, `dashboard_data_mart.py:292`,
  `export_snapshot.py:74`, `gdb_schema.py:416`, `import_rtk_survey.py:107`,
  `upgrade_schema.py:75`, `import_drone_products.py:198`.
- Cargo-cult composite: `dashboard_data_mart.py:292-293` does C *and* imports
  `arcpy_env` unused (`# noqa: F401`) — evidence that batch authors copy the
  incantation without knowing which one is canonical.

Style C evades the one seam (`runtime.sessions.arcpy_env`) the guard
architecture is built around, and the mixing means a reviewer cannot grep for
one pattern to audit the boundary. Note also that A/B create a quiet
**core → runtime** package dependency (upward, against the layering); it is
harmless today only because `sessions.py` is 52 lines, dependency-free, and
lazy.

**Recommendation:** pick style B (function-scope `arcpy_env`) as canonical,
document it in one paragraph (CLAUDE.md or a 10-line ADR including the
sanctioned core→runtime exception), and let the existing `envmon-spec-checker`
agent flag raw `import arcpy` in core. Converting existing A/C sites is *not*
urgent — the value is stopping the fourth style from appearing.

### M2. The `.pyt` is a coverage hole

`toolbox.pyt` is 695 lines of `getParameterInfo`/`execute` logic with zero
automated verification — it cannot be imported headless (top-level
`import arcpy`, by design), and until this review nothing even parsed it, so a
syntax error would first be discovered inside ArcGIS Pro. The
`toolbox_core.py` seam that exists precisely to make adapter logic testable
covers **only the harvester** (`build_harvest_config`/`run_harvest`); all ten
envmon `.pyt` tools marshal parameters inline in `execute()`.

Mitigation added in this review: an AST-parse test
(`tests/test_boundary_imports.py::test_pyt_toolbox_parses`). Remaining
recommendation: when a `.pyt` `execute()` next grows beyond a pass-through
(e.g. `FullPipeline`, `toolbox.pyt:527-609`), move its marshalling into
`toolbox_core.py` per the existing pattern instead of growing inline logic
that can only be tested inside Pro.

### M3. Shared-helper adoption decays batch by batch

The common substrate is good; each batch reuses less of it than the last:

- `common/records_csv.py` (generic dataclass↔CSV round-tripper, fan-in 22
  overall): only **3** envmon modules use it, while **13** hand-roll
  `csv.DictWriter` writers. Two are line-for-line reimplementations of
  `write_records_csv`: `build_exceedance_event.py:174-184
  (write_exceedance_event_csv)` and `event_changelog.py:228-237
  (write_changelog_csv)` — both iterate `dataclasses.fields` → `DictWriter` →
  `asdict`. (Several others write plain dict rows, which is fine.)
- `qa_report_options` decorator (`cli.py:12-26`, the declared "one home" for
  the `--report/--fail-on` contract): 18 adopters, but ~9 commands still
  declare the options by hand (`cli.py:139, 209, 319, 387, 424, 463, 525,
  623, 740`, …) — most predate the decorator and were never migrated.
- `_render_qa` (fan-in 55) is the QA-rendering convention, yet `agol
  publish-layer` (`cli.py:1447-1460`) prints records with an ad-hoc loop and a
  bare `SystemExit(1)`.
- `validate_config.safe_load` (the defensive config-load helper, fan-in 29) is
  reused by exactly one sibling (`validate_units.py`); 4 modules call
  `yaml.safe_load` directly with their own error handling.

None of these is individually a bug. The aggregate is the drift the review
was asked to find: **each autonomous batch re-solves solved problems, slightly
differently.** Recommendation: a one-page "new envmon tool checklist" (blessed
helpers: `QACollector` + `_render_qa` + `qa_report_options`, `records_csv` for
dataclass tables, `load_config`/`safe_load` for YAML, `arcpy_env` style B) —
and make the `envmon-spec-checker` agent check against it. That converts
convention from tribal memory into a gate the next batch actually hits.

### M4. The record-dataclass naming rule is real but undocumented

Two conventions coexist, and the rule separating them is implicit:
GDB-mirroring records use PascalCase fields matching GDB columns 1:1
(`gdb_schema.py:345-389`, `AnalyticalResultRecord` et al. — this is what makes
`records_csv` round-trips produce deliverable-ready column names), while
internal records use snake_case with an explicit mapping (`QARecord`,
`common/qa.py:29-57`, `as_gdb_row()`). Batches guess: `sampling_plan.py:30`
(PascalCase, never touches a GDB) vs its same-PR sibling
`field_lab_reconciler.py:20` (snake_case). Write the rule down — one paragraph
in an ADR ("PascalCase iff the dataclass mirrors a GDB table / deliverable CSV
schema; snake_case otherwise") ends the guessing.

---

## LOW

- **L1. Stale counts/docs drift with every batch.** CLAUDE.md still says "23
  envmon modules" (85) and "151 arcpy-free tests" (1,084 after this review);
  `guard.py` said "the 7 arcpy-touching envmon tools" (~20 LOCAL entries) and
  `envmon/__init__.py` said 23 modules — the latter two fixed here by removing
  the hardcoded counts. Recommend the CLAUDE.md refresh drop numerals entirely
  (they rot within a week at current batch velocity); left to the maintainer
  since CLAUDE.md is policy-sensitive.
- **L2. `common/seen.py` has zero production importers** (`FilesystemSeenIndex`
  / `SetSeenIndex` / `SeenIndex` are imported only by `tests/test_seen.py`),
  yet CLAUDE.md advertises the "seen-index" as part of the common substrate.
  The harvester's `skip_existing`/`incremental` paths use `manifest.py` /
  `state.py` instead. Not proposing deletion (dynamic-use rules apply); either
  wire it in or annotate it as future-use so the next reviewer doesn't re-derive
  this.
- **L3. Import-style drift inside envmon**: most modules use relative imports
  (`from .gdb_schema import …`) per the package docstring; a few use absolute
  (`edd_importer.py:11-13`, `export_geojson.py:15`,
  `schedule_vs_actual.py:29`). Cosmetic; worth one line in the checklist (M3).
- **L4. `normalize_soil/metals/ibi.py` are 2-line re-export shims** over
  `table_normalizer.py`. Fine as deliberate back-compat — but nothing says so;
  a one-line comment ("kept as import-stable seam for profiles/tests") would
  prevent a future "cleanup" from breaking importers.
- **L5. Docs sprawl**: `docs/adr/` + `docs/decisions/` + `docs/logs/` + ~15
  flat top-level roadmap/status files. The ADR dir is healthy (29 ADRs, real
  decisions); the rest accretes per-batch. A `docs/README.md` index or a
  status→archive convention would keep it navigable.

## What is explicitly healthy (do not "fix")

- **The arcpy-free boundary holds.** Full-package import walk passes with
  `arcpy`/`arcgis` absent; `runtime/sessions.py` is genuinely lazy;
  `common/logging.py`'s `_ArcpyHandler` defers correctly; `harvester.py:11`
  guards its `arcgis` import. Now mechanically enforced
  (`tests/test_boundary_imports.py`).
- **`QACollector` is a real architectural win** — thread-safe, universally
  adopted (65/85 modules, fan-in 106 on `.add`), with three report writers and
  a single severity model. This is what convergence looks like; M3's ask is to
  replicate this success for the other helpers.
- **`gdb_schema.AnalyticalResultRecord` as the record hub** (imported by ~10
  modules) and the `normalize_* → table_normalizer → excel_profile_reader`
  chain: coherent, single-direction dependency flow inside envmon. No circular
  imports found.
- **The guard architecture** (`guard.require_runtime` →
  `capabilities.requires_arcpy`, CLI `_guard` mapping `KeyError` to a clean
  ClickException at `cli.py:76-85`) is the right shape; H3 is about feeding it
  reliably, not changing it.
- **`HarvestConfig` canonical-home + re-export** and `toolbox_core`'s
  build-time validation (`config.layer_ref()` tripped at construction) — sound,
  intentional, documented (ADR-0003, MERGE_PLAN §2). Leave alone.
- Pre-production stubs (screening levels `_TODO` sources, H281 DRAFT profile,
  `manage_screening_levels` DRAFT banner) verified intact — untouched by this
  review, per standing instruction.

## Fixes made in this review (deliberately minimal)

1. `tests/test_boundary_imports.py` (new): imports every `autogis` module with
   arcpy/arcgis absent and asserts neither lands in `sys.modules`; AST-parses
   `toolbox.pyt`. Mechanizes the repo's #1 invariant.
2. `cli.py` `import-gdb` redirect message: `HarvestAttachments` →
   `ImportToGdb` (pointed users at the wrong `.pyt` tool).
3. `cli.py` `build-callouts` redirect message: `BuildFigureDataset` (no such
   `.pyt` tool) → `BuildCallouts`.
4. `guard.py` docstring: dropped the stale "7 tools / registered in both"
   claim (H2 documents the real state).
5. `common/config.py` docstring: removed reference to
   `adapters/config_loader.py`, retired in commit `d61e6a6`.
6. `envmon/__init__.py`: dropped the hardcoded "23 modules".

No tests pinned the corrected strings. Suite after changes: **1084 passed**
(1082 baseline + 2 new).

## Suggested order of attack

1. H3 registry-consistency test (smallest change, stops active drift class).
2. H1 run-history adapter hook (one seam, unblocks three shipped consumers).
3. H2 ADR + guard-message branch (a decision plus ~20 lines; also resolves the
   5.2/5.3 dead ends).
4. M3/M4 checklist + naming ADR (paper, not code — then enforced by the
   spec-checker agent).
5. M1 canonical arcpy style (opportunistic, per-file as they're next touched).
