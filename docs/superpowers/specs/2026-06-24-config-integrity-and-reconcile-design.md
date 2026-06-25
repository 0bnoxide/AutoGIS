# Config Integrity & Sample-Location Reconciliation — Design

**Date:** 2026-06-24
**Status:** Approved (design); pending implementation plans
**Round:** Feature ROI Round 2 — the three highest-impact "prevention" features
**Source ranking:** `docs/FEATURE_ROI_ANALYSIS_ROUND2.md` (Tier 1 recommended set)

## Goal

Implement the three highest-impact prevention features from the Round 2 ROI
analysis:

1. **ValidateEnvConfig** — catch bad/inconsistent configs before runs fail.
2. **ManageAnalyteDictionary** — curate/validate the analyte dictionary (read-only).
3. **ReconcileSampleLocations** — pre-flight check that workbook location IDs match
   the well feature class, before import.

The remaining 11 Round 2 candidates stay catalogued in the ROI doc for future
rounds.

## Delivery strategy

**One design (this document), two implementation plans / PRs:**

- **Phase A — Config Integrity:** shared `config_validation` core + `ValidateEnvConfig`
  + `ManageAnalyteDictionary`. All headless, low-risk, share the validator core.
  Ships independently and unblocks nothing else (pure quick win).
- **Phase B — ReconcileSampleLocations:** standalone pre-flight tool. Different
  domain (data ↔ feature-class reconciliation), carries the only fuzzy-matching
  complexity and the only production arcpy dependency.

Splitting delivery keeps the three easy config wins from being held hostage to
Reconcile's complexity, and yields two focused, independently testable PRs. The
design narrative stays unified here.

## Unifying architecture

All three tools are **read-only QA producers**. Each builds a `QACollector`
(`core/common/qa.py`), runs checks that `add()` `QARecord`s, then renders via the
existing `write_markdown` / `write_json_summary` / `write_csv` writers and exits
non-zero when `status()` is `FAIL`. No new reporting infrastructure — this mirrors
`core/envmon/validate_database.py` exactly.

This keeps every tool **ADR-002 compliant** (arcpy-free core), consistent with the
existing suite, and aligned with **ADR-001** (core logic + thin adapters) and
**ADR-003** (canonical config locations).

### Where validator logic lives

Chosen approach: a single new module of **pure `data -> List[QARecord]`
functions**.

```
core/common/config_validation.py   NEW  pure validators -> [QARecord]   (Phase A)
core/envmon/validate_config.py      NEW  ValidateEnvConfig orchestrator  (Phase A)
core/envmon/manage_analyte_dict.py  NEW  inspect/report over analyte validator (Phase A)
core/envmon/reconcile_locations.py  NEW  headless reconcile core         (Phase B)
adapters/cli.py                     EDIT new commands (3)
<.pyt toolbox>                      EDIT .pyt tool for reconcile's arcpy well read (Phase B)
tests/envmon/                       NEW  unit tests (all headless)
```

Validators are dumb and side-effect-free: they receive already-loaded `dict`/
dataclass data and return records. Tools own file I/O and orchestration. This makes
the analyte validator shared verbatim by both ValidateEnvConfig and
ManageAnalyteDictionary, and makes every validator unit-testable with no arcpy and
no file system.

Rejected alternatives: adding `validate()` methods onto the `config.py` dataclasses
(bloats an already-369-line module; mixes load-time `raise` semantics with
collect-all `QARecord` semantics); a multi-file `validation/` package (more files
than the current logic warrants).

## Shared contract — report & exit codes (all three tools)

- Build a `QACollector`; render markdown to stdout; optional `--report PATH.{md,json,csv}`.
- **Exit codes:** `0` = PASS, `1` = FAIL (blocking per `status()`), `2` = tool/usage error.
- **`--fail-on error|warning`** (default `error`): selects whether warnings are
  blocking. `--fail-on warning` tightens for CI gates.
- `_TODO` / DRAFT markers always surface as **WARNING** (category `placeholder`),
  never silently passed — honors the CLAUDE.md invariant that DRAFT/`_TODO` markers
  must not be removed/ignored until verified against real data.

`QARecord` fields used: `severity`, `category`, `message`, `recommended_action`,
plus context fields where relevant (`site_id`, `location_id`, `analyte_name`,
`source_workbook`, `source_sheet`, `source_column`).

---

## Phase A — Tool 1: ValidateEnvConfig

### Validation unit: per-bundle from explicit args

Site configs do **not** declare their parser profile or figure specs today — the
CLI passes them as separate arguments per run (`cli.py` commands accept
`site_config`, `figure_spec`, workbook as independent paths). So validation
assembles the bundle from explicit arguments, matching how runs actually work. No
config-schema change.

### CLI

```
autogis envmon validate-config SITE.yaml
    [--profile P.yaml]...      # zero or more parser profiles
    [--figure F.yaml]...       # zero or more figure specs
    [--analytes A.yaml]        # default: config/analytes/analyte_dictionary.yaml
    [--screening S.yaml]       # default: config/screening_levels/screening_levels.yaml
    [--report OUT.{md,json,csv}]
    [--fail-on error|warning]
```

Each file is loaded defensively: a `ConfigError` becomes an ERROR `QARecord`
(category `load_error`) rather than crashing the tool, so one bad file never hides
problems in the others.

### Checks

Per-file validators (each `data -> [QARecord]`):

- **`validate_site`** — required keys present; `map_units ∈ {feet, meters}` and
  consistent with `coordinate_system`; `plausible_gwe_range_ft` is a 2-element
  ascending numeric list; relative `default_gdb` / `default_aprx_template` resolve
  against the config file's directory; `_TODO` values → `placeholder` warnings.
- **`validate_parser_profile`** — `profile_id` + `sheets` present; each sheet has a
  recognized `data_type`; column references resolve (`col_index` does not raise);
  `analyte_columns` range is sane; row anchors are positive ints where set.
- **`validate_figure_spec`** — required keys (`FIGURE_REQUIRED`); `map_type` /
  `matrix` in allowed sets; declared analyte sets non-empty.
- **`validate_analyte_dictionary`** — shared with Tool 3 (see below).
- **`validate_screening_levels`** — matrix keys are known matrices; each entry has
  `value` + `units`.

Cross-file validator (the headline value — nothing does this today):

- **`validate_bundle`** —
  - figure-spec analyte lists ⊆ analyte dictionary (canonical names + aliases);
  - screening-level analytes ⊆ analyte dictionary;
  - parser-profile `data_type`s cover what supplied figure specs need;
  - units coherence: screening-level units vs analyte `default_units_by_matrix`.

---

## Phase A — Tool 3: ManageAnalyteDictionary

### Read-only (validate + inspect; no writes)

Decision: the tool does **not** mutate `analyte_dictionary.yaml`. The file is
hand-curated with load-bearing comments ("DO NOT invent regulatory numbers here")
and `_TODO` markers; a PyYAML `safe_dump` round-trip would destroy them, and
`ruamel.yaml` is not in the environment. Edits stay manual. The tool reuses the
**same** `validate_analyte_dictionary` that ValidateEnvConfig's bundle uses.

### CLI

```
autogis envmon manage-analyte-dict ANALYTES.yaml [--list] [--check] [--report OUT]
```

- **`--check`** (default): runs `validate_analyte_dictionary` —
  - duplicate canonical names;
  - **alias collisions** (one alias normalizing to two different analytes);
  - duplicate `display_order` values;
  - missing/invalid required fields per entry;
  - `default_units_by_matrix` sane;
  - `_TODO` in `screening_level_source` → `placeholder` warnings.
- **`--list`**: prints the resolved table (canonical name, abbreviation,
  analytical_group, display_order, alias count, `include_in_default_figures`)
  sorted by `display_order` — a human curation aid.

Alias normalization reuses the existing `normalize_analyte_name` rule
(case/whitespace/punctuation-insensitive) referenced by the dictionary header.

---

## Phase B — Tool 2: ReconcileSampleLocations

### Standalone pre-flight, read-only

Its own command, run **before** importing. Reports matches / misses / fuzzy
suggestions so the user fixes the workbook or the well layer, then imports cleanly.
Not integrated into ImportToGdb (keeps Tool 2's arcpy path unchanged and lets the
check run headless).

### CLI

```
autogis envmon reconcile-locations SITE.yaml WORKBOOK.xlsx
    --profile P.yaml
    [--wells-csv W.csv | --gdb]
    [--threshold 0.8]
    [--report OUT.{md,json,csv}]
    [--fail-on error|warning]
```

### Headless core

```python
reconcile(workbook_ids: list[str], well_ids: list[str], threshold: float)
    -> ReconcileResult
```

Normalization: uppercase, strip, collapse `-_<space>` separators. Outputs:

- **exact matches** (post-normalization);
- **unmatched workbook IDs**, each with best fuzzy suggestion ≥ threshold via
  stdlib `difflib.SequenceMatcher` (**no new dependency**);
- **unmatched well IDs** (present in layer, absent from workbook).

Record severities:

- unmatched workbook ID **with** suggestion → WARNING (category
  `location_id_typo`, `recommended_action` names the suggestion);
- unmatched workbook ID **without** suggestion → ERROR (category
  `location_id_unmatched`);
- unmatched well ID → INFO (category `well_not_sampled`).

### Headless boundary / data sources

- Workbook location IDs: read via the parser profile's `id_column` /
  `sample_id_column` using openpyxl — headless.
- Well IDs: from **`--wells-csv`** (headless; also the unit-test path) or
  **`--gdb`** (production; thin arcpy `SearchCursor` on
  `monitoring_wells_fc.LocationID`, mirroring `validate_database._read`).
- A `.pyt` tool wraps the `--gdb` path for the toolbox UI. The `reconcile` algorithm
  itself never imports arcpy (ADR-002).

---

## Testing

All headless; extends the existing 132-test arcpy-free suite (`python -m pytest -q`).

- **`config_validation`** — table-driven good/bad fixtures per validator; explicit
  cross-file mismatch cases (figure analyte absent from dictionary; screening
  analyte absent; units mismatch).
- **`manage-analyte-dict`** — duplicate canonical name, alias collision, duplicate
  `display_order`, missing-field fixtures; `--list` output snapshot.
- **`reconcile`** — exact match, typo → suggestion, no-match (ERROR), extra well
  (INFO), threshold-boundary; driven by in-memory ID lists and `--wells-csv` (no
  arcpy).

## Explicit YAGNI / scope boundaries

- **No** analyte-dictionary writes (read-only curation).
- **No** config auto-discovery / whole-tree sweep — per-bundle from args only.
- **No** Reconcile auto-fix — suggest-only, read-only.
- **No** new fuzzy-matching dependency — stdlib `difflib`.
- **No** site-config schema change (no `parser_profile:` / `figure_specs:` keys).

## Open items for implementation planning

- Confirm the exact `.pyt` toolbox file and tool-registration pattern for the
  Reconcile `--gdb` wrapper (Phase B).
- Confirm the canonical "allowed sets" for figure `map_type` / `matrix` and parser
  `data_type` (read from existing config + code constants during Phase A).
- Confirm `normalize_analyte_name` location and signature for reuse in the analyte
  validator.
