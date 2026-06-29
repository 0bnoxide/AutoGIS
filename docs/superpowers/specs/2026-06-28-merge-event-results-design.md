# MergeEventResults Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** MergeEventResults (Phase 2 / Tool 2.10)
**Priority:** HIGH — foundation for all cross-event analysis tools

---

## Problem

EnvMon sites produce one result CSV per sampling event. Cross-event analysis
tools (`build-max-result-dataset`, `generate-change-log`, `build-compliance-table`)
all require a single merged long-format table. Currently analysts manually
concatenate CSVs, strip duplicates by hand, and forget to add an event-date
column — making the merged output impossible to trace back to its source events.
Mistakes propagate into every downstream analysis.

---

## Approach

**Chosen:** Directory-scan or explicit file list merge. Reads N result CSVs,
adds `EventLabel` and `EventDate` columns (inferred from filename pattern or
from a sidecar manifest), deduplicates on the canonical key
`(SampleID, AnalyteName, ReportedUnits)`, and writes a single merged long-format
CSV. SHA-256 hashing of source files written to merge manifest for traceability.

Filename pattern to infer event date: `Env_Results_YYYYMMDD*.csv` or
`*_Q[1-4]_YYYY*` — configurable via regex.

**Rejected: Requiring a manifest file.** A manifest is generated automatically
when not provided; analyst can review it after the fact.

**Rejected: Pandas.** Pandas is not a core dependency; pure csv module handles
this workload.

---

## Architecture

```
autogis/
  core/envmon/
    event_results_merger.py       ← NEW
  adapters/
    cli.py                        ← add merge-event-results command (headless)
tests/envmon/
  test_event_results_merger.py    ← NEW
```

---

## Public API (`event_results_merger.py`)

```python
@dataclass
class SourceFile:
    path: Path
    event_label: str      # e.g. "Q1-2026"
    event_date: str       # ISO date inferred or explicit
    sha256: str
    row_count: int

@dataclass
class MergeResult:
    merged_path: Path
    manifest_path: Path
    source_files: list[SourceFile]
    total_rows: int
    duplicate_rows_dropped: int
    qa: QACollector

def infer_event_label(path: Path, pattern: str = r"(\d{8})") -> str:
    """Extract date/label from filename via regex; fallback to stem."""

def merge_event_results(
    source_paths: list[Path],
    out_path: Path,
    *,
    event_labels: list[str] | None = None,  # parallel to source_paths
    dedup_key: tuple = ("SampleID", "AnalyteName", "ReportedUnits"),
    add_source_column: bool = True,
    manifest_path: Path | None = None,
    qa: QACollector | None = None,
) -> MergeResult:
    """
    Concatenate CSVs, optionally add EventLabel + EventDate columns,
    deduplicate on dedup_key (keep first), write merged CSV + manifest.
    """

def write_merge_manifest(source_files: list[SourceFile], manifest_path: Path) -> None:
    """Write CSV manifest: source_file, event_label, sha256, row_count."""
```

---

## CLI Command

```
autogis envmon merge-event-results \
  --results <file1.csv> --results <file2.csv> ... \
  [--results-dir <dir_with_csvs>] \
  [--event-labels Q1-2026,Q2-2026] \
  [--out <merged_results.csv>] \
  [--manifest <merge_manifest.csv>] \
  [--no-dedup] \
  [--report <qa.md>]
```

Headless.

---

## Test Strategy

`tests/envmon/test_event_results_merger.py` — arcpy-free:

1. Two CSVs with no overlap → merged row count equals sum of both
2. Duplicate row (same SampleID/AnalyteName/Units) → deduplicated, count logged
3. `infer_event_label` extracts YYYYMMDD from filename
4. `EventLabel` column added to merged output
5. Manifest CSV written with sha256 and row_count per source file
6. Missing source file → ERROR in QA, merge continues with remaining files
7. Single file → valid merge (no-op but correctly structured)
8. `add_source_column=False` → no EventLabel column in output
