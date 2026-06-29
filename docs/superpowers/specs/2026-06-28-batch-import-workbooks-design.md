# BatchImportEnvironmentalWorkbooks Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** BatchImportEnvironmentalWorkbooks (Tool 2.2)
**Priority:** HIGH — scales the single-workbook importer across many small sites

---

## Problem

The single-workbook path (`result_parser.py` + parser profiles) imports one report
workbook at a time. Multi-site programs receive a folder of dozens of workbooks per
quarter, each needing the correct parser profile chosen by site. `batch-edd-import`
already exists but only handles *EDD* CSV/XLSX (the clean lab export format). The ugly
*report workbooks* — the ones parser profiles exist for — have no batch driver. Analysts
loop them by hand, with no manifest or per-file QA roll-up.

---

## Approach

**Chosen:** Folder driver over the existing single-workbook parser. For each workbook in
the input folder, route it to a parser profile by (1) explicit site-lookup row, else
(2) filename pattern, else (3) workbook content sniff — first match wins, ambiguity is a
QA WARNING. Run the existing `result_parser` per file, collect normalized records, and
write a batch manifest + a merged QA report. Import mode controls write behavior:
`validate` (no write), `append`, `replace-event`, `replace-batch`.

**Rejected: re-implementing parsing.** This is purely an orchestration layer over
`result_parser` — it owns routing, manifest, and QA aggregation, nothing else.

**Rejected: merging with `batch-edd-import`.** Different input shapes (report workbook +
profile vs. EDD). Both reuse the same `QACollector`/manifest helpers; folding them would
couple two unrelated parsers.

**Geodatabase writes** for `append`/`replace-*` are arcpy-bound and route through the
`.pyt` toolbox seam (ADR-0006). The headless CLI supports `validate` fully and emits the
normalized CSVs + manifest; the gdb write step guards-and-redirects per the Tools 2–8
pattern (CLAUDE.md).

---

## Architecture

```
autogis/
  core/envmon/
    result_parser.py        ← EXISTS (reused per workbook)
    batch_workbooks.py      ← NEW (routing + manifest + QA roll-up)
  adapters/
    cli.py                  ← add batch-import-workbooks (validate headless;
                              append/replace guard+redirect to .pyt)
tests/envmon/
  test_batch_workbooks.py   ← NEW
```

---

## Public API (`batch_workbooks.py`)

```python
@dataclass
class WorkbookRouting:
    workbook: Path
    profile: Path | None
    site_id: str | None
    route_method: str        # site_lookup | filename | content | unrouted
    qa_note: str

@dataclass
class BatchImportResult:
    routings: list[WorkbookRouting]
    normalized_rows: list[dict]   # combined EnvAnalyticalResult-shaped rows
    manifest: list[dict]          # per-workbook: rows, errors, warnings, profile
    qa: QACollector

def route_workbooks(
    folder: Path,
    *,
    site_lookup: dict[str, str] | None = None,   # filename/stem -> site_id
    profile_dir: Path,
) -> list[WorkbookRouting]:
    """Resolve each workbook to a parser profile; unrouted -> ERROR."""

def run_batch_import(
    folder: Path,
    *,
    profile_dir: Path,
    site_lookup_path: Path | None = None,
    mode: str = "validate",       # validate | append | replace-event | replace-batch
) -> BatchImportResult:
    """Route + parse every workbook; aggregate manifest and QA."""

def write_manifest(result: BatchImportResult, out_path: Path) -> Path:
    """CSV import manifest, one row per workbook."""
```

---

## CLI Command

```
autogis envmon batch-import-workbooks \
  --folder <workbooks/> \
  --profile-dir <profiles/> \
  --out-dir <out/> \
  [--site-lookup <sites.csv>] \
  [--mode validate|append|replace-event|replace-batch] \
  [--report <batch_qa.md>]
```

`validate` is headless. `append`/`replace-*` guard then redirect to the `.pyt` toolbox.

---

## Test Strategy

`tests/envmon/test_batch_workbooks.py` — arcpy-free:

1. Site-lookup routing wins over filename when both present.
2. Filename-pattern routing used when no lookup row.
3. Unrouted workbook → ERROR in QA, `route_method == "unrouted"`.
4. `run_batch_import(mode="validate")` parses all and writes no gdb.
5. Manifest has one row per workbook with row/error/warning counts.
6. Per-workbook parse errors aggregate into the batch QA without aborting the batch.
7. `append`/`replace-*` modes raise the capability guard when arcpy is absent.
