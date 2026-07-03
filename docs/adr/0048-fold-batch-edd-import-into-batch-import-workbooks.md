# ADR-0048: BatchEDDImport folded into Tool 2.2 `batch-import-workbooks` — alternate input mode, not a new tool

**Status:** Accepted

**Date:** 2026-07-03

## Context

The post-roadmap item BatchEDDImport (plan:
`docs/superpowers/plans/2026-06-28-batch-edd-import.md`) proposed a new
module `core/envmon/batch_edd.py`, a new `BatchImportSummary` dataclass, and
a new CLI command `batch-import-edd` that would process a directory of EDD
files with one shared profile/site.

Tool 2.2 `batch-import-workbooks`
(`core/envmon/batch_workbook_importer.py`) already does headless batch EDD
import: it composes `read_edd_file()` + `normalize_edd_rows()` per file,
catches per-file failures into a manifest report without aborting the batch,
and aggregates into `sample_records.csv`/`result_records.csv`. The only
functional gap was input shape — Tool 2.2 required a manifest CSV
enumerating `(workbook_path, profile_path, site_id)` per row, while the
roadmap wanted a directory glob with one shared profile/site.

The plan was also independently stale: its central reused function
`run_edd_import_csv` never existed (the real functions are
`read_edd_file()`/`normalize_edd_rows()` in `edd_importer.py`), and its
stated dependency plan (`2026-06-28-fix-import-edd-headless.md`) references
a nonexistent `parse_edd()`.

## Decision

**Fold, don't build** (user decision 2026-07-03, recorded in
`docs/superpowers/specs/2026-07-03-planned-roadmap-batch-brief.md` §4):

- `manifest_rows_from_dir(edd_dir, profile_path, site_id, pattern=None)` in
  `batch_workbook_importer.py` synthesizes the existing manifest-row shape
  from a directory glob, then hands off to `run_batch_import()` unchanged.
  Default pattern `*.csv`, falling back to `*.xlsx` when no CSV matches; an
  explicit `--pattern` is used as-is with no fallback.
- The existing `batch-import-workbooks` command gained
  `--edd-dir`/`--profile`/`--site`/`--pattern` options, mutually exclusive
  with `--manifest` (exactly one input mode per invocation, `UsageError`
  otherwise). The manifest-CSV path is unchanged.
- No new module, dataclass, command name, or `_REGISTRY_SEED` entry. The
  existing `BatchImportResult` covers the plan's proposed
  `BatchImportSummary`; per-file failure handling and output shape are
  whatever Tool 2.2 already did.

Config loading in the command body is shared by both input modes (raw
`yaml.safe_load()` for `--analytes`/`--screening`, a pre-existing behavior
inherited unchanged — flagged in the brief as an existing risk, out of scope
here; no new inconsistency between modes was introduced).

## Consequences

- Bulk lab-deliverable import without shell-scripting a manifest:
  `autogis envmon batch-import-workbooks --edd-dir <dir> --profile <yaml>
  --site <id> --output-dir <out>`.
- One importer to maintain; the near-duplicate second importer the plan
  proposed is never built.
- `docs/superpowers/plans/2026-06-28-batch-edd-import.md` carries a
  SUPERSEDED banner pointing here; it must not be implemented as written.
- Suite grows 1516 -> 1522 (six new tests: happy-path directory import,
  per-file failure isolation, mutual-exclusivity/missing-mode/empty-glob
  errors, and the xlsx-fallback helper contract).
