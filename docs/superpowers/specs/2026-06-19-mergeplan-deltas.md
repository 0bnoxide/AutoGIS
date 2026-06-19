# MERGE_PLAN Deltas — Verified Ground Truth (Recon Wave R1–R6)

**Date:** 2026-06-19
**Source plan:** `docs/superpowers/plans/2026-06-19-parallel-recon-dispatch.md`
**Method:** 6 read-only recon agents audited `staging/envmon-incoming/` + `autogis/`
against MERGE_PLAN claims. This doc is verified ground truth; where it differs
from `docs/MERGE_PLAN.md`, **this doc wins** (MERGE_PLAN itself says don't trust
its summary over the code).

---

## 1. Verdict table

| Stream | Claim | Verdict | Delta (short) |
|---|---|---|---|
| R1 | 14 of 23 src modules arcpy-free, named list | **confirmed** | none |
| R1 | 8 named arcpy-edge modules, all lazy-import | **confirmed** | none — zero top-level arcpy |
| R1 | "import succeeds w/o arcgis NOR arcpy" | **corrected** | `logging_utils` is a 9th arcpy-touching module (lazy, safe); many modules hard-require **openpyxl** to import |
| R2 | flat non-namespaced sibling imports to rewrite | **confirmed** | full adjacency + topo order captured; no cycles |
| R2 | sys.path hack in the `.pyt` | **confirmed** | lines 14–16 (delete 14 too — dead var) |
| R3 | "56 tests" | **confirmed** | 56 = 29 fns + 28 parametrize cases; 4 files |
| R3 | arcpy paths un-CI-able / pure core testable | **confirmed** | **all 56 are pure-python / CI-able; 0 Pro-only** |
| R4 | envmon config = typed dataclasses w/ `.load()` | **corrected** | 4th dataclass `SheetProfile`; "typed" is **two** styles (dict-backed vs field-typed) |
| R4 | §3.1 adopt envmon convention, re-express HarvestConfig | **needs-human** | underspecifies `(config,profile)` tuple, nested flattening, override whitelist, url/item_id XOR |
| R5 | QACollector richer; standardize on it | **confirmed** | naming: writer is `write_json_summary` (summary, not per-record) |
| R5 | `RunSummary.record`/`Manifest.add` not thread-safe | **confirmed** | unsafe surface **broader**: iterating writers + all of `QACollector` too |
| R5 | provenance fields (checksum/geometry/source_table/relationship_id) absent | **confirmed** | absent; `QARecord` provenance ≠ harvester provenance |
| R5 | fold counters in as "small summary view over QA records" | **needs-human** | outcome-axis vs issue-axis mismatch; needs a disposition decision |
| R6 | H281 profile is unverified DRAFT | **confirmed** | none — banner + `_TODO`s + README gate present |
| R6 | arcpy paths untested outside Pro | **confirmed** | none |
| R6 | `average_parent_and_duplicate` emits QA WARNING | **confirmed** | none — warns on both averaged + nondetect-pair |
| R6 | screening-levels ships all-null + `_TODO` | **confirmed** | none — 45 null entries |

---

## 2. Corrections to MERGE_PLAN (change build instructions)

**C1 (R1) — the arcpy module count is 14 + 9, not 14 + 8.**
`logging_utils.py` is a ninth arcpy-touching module. arcpy is lazily imported
inside `_ArcpyHandler.emit()` (in a try/except), so module import is still safe.
MERGE_PLAN's explicit lists omit it. Build impact: when moving modules and
applying the runtime guard, treat `logging_utils` as arcpy-edge (lazy), not
arcpy-free. The "neither arcgis nor arcpy to import" rule still holds.

**C2 (R1) — `openpyxl` is a hard import-time dependency for much of the core.**
`envmon_config`, `excel_profile_reader`, and everything importing them fail at
import without `openpyxl` (a `ModuleNotFoundError` unrelated to arcpy/arcgis).
Build impact: `openpyxl` must be a **base** dependency of the package (not an
extra). The "import with neither arcgis nor arcpy" rule is about arcpy/arcgis
only; openpyxl is assumed present.

**C3 (R2) — relative-import rewrite order (step 4) is fixed and acyclic.**
No circular imports. Migrate roots first, in this topological order:
```
callout_templates, logging_utils, qa_checks, result_parser, envmon_config,
callout_geometry, callout_collision, build_figure_dataset, gdb_schema,
export_figures, groundwater_contours, layout_manager, excel_profile_reader,
validate_database, excel_workbook_inspector, table_normalizer,
normalize_groundwater, normalize_rpd, normalize_metals, normalize_soil,
normalize_ibi, import_to_gdb, build_current_event
```
Delete `.pyt` lines **14–16** (the `_SRC` var + the two `sys.path.insert` lines).

**C4 (R3) — all 56 tests are CI-able; the CI gate covers the full pure core.**
0 tests are Pro-only. Step 4's CI gate is `pytest tests/` over the ported
suite with `PYTHONPATH`/package install; no test needs Pro. (arcpy *tools*
2–8 remain manually-verified, but their pure logic is covered by these 56.)

**C5 (R4) — envmon config is TWO dataclass styles + a 4th class.**
`SheetProfile` exists (field-typed, the richest). `ParserProfile`/`SheetProfile`
are field-typed; `SiteConfig`/`FigureSpec` are **dict-backed `__getattr__`
wrappers** (raw `data: dict` + `path`). Build impact: do NOT re-express
`SiteConfig`/`FigureSpec` with explicit fields — that breaks callers/tests
relying on arbitrary-key passthrough (`default_analyte_set`, `analyte_sets`).
Re-express only `HarvestConfig` in the field-typed style (it fits cleanly).

**C6 (R5) — thread-safety work is bigger than the two named methods.**
The unsafe surface includes `RunSummary.record`, `Manifest.add` **and**
`Manifest.write_csv/write_json/write` (iterate-while-append) **and** all of
`QACollector` (`add`/`extend`/readers/writers). No locks exist anywhere in
`autogis/`. Build impact (step 2 reporter): lock the whole shared-state surface,
not just `record`/`add`, or parallel downloads still race.

**C7 (R5) — envmon has no per-record JSON writer.**
`write_json_summary` emits an aggregate (counts/status/record_count), NOT a
per-record dump like harness `Manifest.write_json`. Build impact: the unified
reporter must ADD a per-record JSON writer, not just rename — else the
per-record `manifest.json` consumers lose their feed.

---

## 3. needs-human queue (decide before / during build)

**H1 (R4, highest-risk §3.1 gap) — how to fold the harness loader's extra
responsibilities into envmon's single-object `.load(path)` style.** Four things
have no clean home in `.load(path) -> object`:
- the `(HarvestConfig, profile)` **tuple** return — `profile` is `connection.profile`
  (auth/session data, not harvest config); §7 still lists the tuple signature.
- the **nested→flat** YAML mapping (harness YAML has `connection/layer/output/options`
  sections; envmon `load_config` reads a flat top-level mapping).
- the CLI **override whitelist** (`_OVERRIDE_KEYS = where/directory/incremental`);
  envmon `.load(path)` takes no overrides.
- the **(item_id XOR url)** invariant, today enforced lazily in `layer_ref()`,
  not at construction — doesn't fit envmon's `_require` flat-missing-keys model.
- *Decision needed:* does `HarvestConfig.load` return `(config, profile)` and take
  `overrides=`, OR does `profile` move to `runtime/sessions.py` (§3.4) and
  overrides stay an adapter concern? Either way, validation (incl. url/item_id)
  must live on the dataclass per §2's single-validation-source rule.
- *Risk if ignored:* breaks CLI auth (profile) and/or `--where/--out/--incremental`
  flags, or defers validation past load (opposite of §2).

**H2 (R5) — counter-fold disposition modeling.** Harvester counters
(`downloaded/skipped/failed`) are an **outcome** axis; `QARecord` is an
**issue** axis (`severity`+`category`). A successful download emits a manifest
row but **no** QARecord today, so "counters as a view over QA records" would
count 0 downloaded. *Decision needed:* either (a) the unified result record
carries an explicit **disposition/outcome field**, or (b) successes/skips emit
INFO-severity QA records under a reserved category. Decide before step 2.

**H3 (R6, carry-forward gate — do not regress) — H281 profile verification.**
The H281 parser profile is a confirmed unverified DRAFT (banner +`_TODO`s +
README mandate). This does NOT block the merge build, but the merge must
**preserve** the draft designation and the Tool-1 + human-review-before-first-
import gate. Flag for the user: real-workbook verification remains a manual
pre-production task, owned by you, outside this merge.

---

### 3a. needs-human resolutions (user, 2026-06-19)

- **H1 → RESOLVED: move profile to sessions, overrides to adapter.**
  `HarvestConfig.load(path) -> HarvestConfig` (pure envmon single-object style).
  `connection.profile` moves to `runtime/sessions.py` (§3.4); the CLI override
  whitelist (`where/directory/incremental`) becomes a CLI-adapter concern, not a
  loader param. url/item_id-XOR validation lives on the dataclass (§2 single
  validation source). Build impact: §7's `(HarvestConfig, profile)` tuple
  signature is **superseded** — update cli.py wiring to source profile from
  sessions, apply overrides in the adapter before/around `.load`.
- **H2 → RESOLVED: explicit disposition field on the unified result record.**
  The unified record carries an outcome/disposition field (`downloaded/skipped/
  failed`); summary counts group by it. QA records stay issue-only — successes
  do NOT emit QA records. Build impact (step 2 reporter): summary view groups by
  disposition field, not by QA severity/category.
- **H3 → ACKNOWLEDGED: preserve the H281 draft gate.** Merge keeps the DRAFT
  banner + `_TODO`s + Tool-1/human-review-before-first-import gate un-regressed.
  Real-workbook verification remains a manual pre-production task owned by the
  user, outside this merge.

## 4. Import graph + topological order (R2 — step 4 consumes directly)

**Adjacency list (module -> sibling imports):**
```
build_current_event   -> [envmon_config, logging_utils, qa_checks]
build_figure_dataset  -> [callout_collision, callout_geometry, callout_templates, logging_utils, qa_checks]
callout_collision     -> [callout_geometry]
callout_geometry      -> [callout_templates]
callout_templates     -> []
envmon_config         -> []
excel_profile_reader  -> [envmon_config, qa_checks]
excel_workbook_inspector -> [qa_checks, result_parser]
export_figures        -> [logging_utils, qa_checks]
gdb_schema            -> [qa_checks]
groundwater_contours  -> [logging_utils, qa_checks]
import_to_gdb         -> [envmon_config, excel_profile_reader, gdb_schema, logging_utils, normalize_groundwater, normalize_ibi, normalize_metals, normalize_rpd, normalize_soil, qa_checks]
layout_manager        -> [logging_utils, qa_checks]
logging_utils         -> []
normalize_groundwater -> [envmon_config, excel_profile_reader, gdb_schema, qa_checks, result_parser, table_normalizer]
normalize_ibi         -> [envmon_config, excel_profile_reader, gdb_schema, qa_checks, table_normalizer]
normalize_metals      -> [envmon_config, excel_profile_reader, gdb_schema, qa_checks, table_normalizer]
normalize_rpd         -> [envmon_config, excel_profile_reader, gdb_schema, qa_checks, result_parser]
normalize_soil        -> [envmon_config, excel_profile_reader, gdb_schema, qa_checks, table_normalizer]
qa_checks             -> []
result_parser         -> []
table_normalizer      -> [envmon_config, excel_profile_reader, gdb_schema, qa_checks, result_parser]
validate_database     -> [gdb_schema, logging_utils, qa_checks]
```
**Topological order (leaves first):** see C3 above. **No circular imports.**
**`.pyt` deletions:** lines 14–16.

---

## 5. Reserved-schema note (R5 — build into core/common now)

The unified result/manifest record in `core/common` must **reserve** these
columns even though the features that fill them ship post-merge:
`checksum` (+`algorithm`), `geometry` (WKT/GeoJSON), `source_table`,
`relationship_id`. Confirmed all absent today; `AttachmentResult` is exactly
`objectid, attachment_id, original_name, saved_path, size, status, error` and
the manifest derives columns dynamically from it. `QARecord`'s provenance
(site/sample/analyte/cell…) is import-QA provenance and does **not** supply the
harvester provenance — add the harvester fields explicitly. Adding them later =
a second manifest-schema migration (the failure HARVESTER_ENHANCEMENTS warns of).
Also: harvester queries with `return_geometry=False` today — GeoJSON support
will need that flipped.

---

## 6. Disposition

- R1, R6: confirmed, low-risk — proceed.
- R2, R3: confirmed with concrete artifacts (import graph, test gate) — feed to step 4.
- R4, R5: confirmed substrate direction, but **3 needs-human decisions (H1, H2, H3)**
  must be resolved before/at steps 1–2 since they shape `core/common`'s config +
  reporter interfaces.
- Corrections C1–C7 feed directly into the build plan's Global Constraints.
