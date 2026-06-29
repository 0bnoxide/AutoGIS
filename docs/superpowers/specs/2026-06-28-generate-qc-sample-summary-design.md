# GenerateQCSampleSummary Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** GenerateQCSampleSummary (Phase 2 / Tool 2.9)
**Priority:** MEDIUM — required for laboratory data validation chapters in monitoring reports

---

## Problem

Every monitoring report requires a QC data summary chapter: method blanks,
field blanks, trip blanks, matrix spikes (MS/MSD), laboratory duplicates
(LD), and field duplicates (FD) are assessed separately from primary samples.
Currently analysts search the EDD manually for QC identifiers, compute spike
recoveries and duplicate RPDs by hand, and paste results into a Word table.
With no automation, this is 1–3 hours per event and prone to transcription errors.

---

## Approach

**Chosen:** QC type classifier + per-type summary workbook. Reads long-format
lab results CSV. Classifies each row by `SampleType` field (or infers from
`SampleID` suffix pattern: `-MB`, `-FB`, `-MS`, `-MSD`, `-LD`, `-FD`).
For each QC type:
- Blank: detect flag (any value above MDL → WARNING)
- MS/MSD: percent recovery = (spiked_result - unspiked) / spike_level × 100
- Duplicate (LD/FD): RPD between pair

Outputs one sheet per QC type in an openpyxl workbook + summary sheet.

**Rejected: Building into EvaluateDuplicateRPD.** That tool handles field
duplicates only. This tool covers all QC types in a unified pass.

**Rejected: Requiring SampleType field.** The tool infers from SampleID suffix
if SampleType is absent, with a WARNING when inference is used.

---

## Architecture

```
autogis/
  core/envmon/
    qc_sample_summary.py         ← NEW
  adapters/
    cli.py                       ← add generate-qc-summary command (headless)
tests/envmon/
  test_qc_sample_summary.py      ← NEW
```

---

## Public API (`qc_sample_summary.py`)

```python
QC_TYPES = (
    "method_blank", "field_blank", "trip_blank",
    "matrix_spike", "matrix_spike_duplicate",
    "lab_duplicate", "field_duplicate",
    "primary",   # normal sample — excluded from QC sheets
)

@dataclass
class QCRecord:
    sample_id: str
    qc_type: str
    location_id: str
    analyte_name: str
    result_value: float | None
    qualifier: str
    units: str
    sample_date: str
    # computed
    rpd: float | None            # for duplicates
    pct_recovery: float | None   # for spikes
    pass_fail: str               # pass | fail | na

@dataclass
class QCSummaryResult:
    records: list[QCRecord]
    blank_detections: int
    spike_failures: int          # recovery outside 70–130%
    duplicate_failures: int      # RPD > threshold (default 30%)
    qa: QACollector

def classify_qc_rows(
    result_rows: list[dict],
    *,
    qc_type_field: str = "SampleType",
    sample_id_field: str = "SampleID",
) -> list[QCRecord]:
    """Classify and compute QC metrics for each row."""

def pair_duplicates(records: list[QCRecord]) -> list[tuple]:
    """Pair MS/MSD and LD/FD records by SampleID prefix + analyte."""

def compute_rpd(val1: float, val2: float) -> float:
    """RPD = abs(v1 - v2) / ((v1 + v2) / 2) × 100"""

def write_qc_summary_workbook(
    result: QCSummaryResult,
    out_path: Path,
    *,
    rpd_threshold: float = 30.0,
    recovery_min: float = 70.0,
    recovery_max: float = 130.0,
) -> Path:
    """Write one sheet per QC type + Summary sheet."""
```

---

## CLI Command

```
autogis envmon generate-qc-summary \
  --results <lab_results.csv> \
  --out <qc_summary.xlsx> \
  [--rpd-threshold 30.0] \
  [--recovery-min 70.0] \
  [--recovery-max 130.0] \
  [--report <qa.md>]
```

Headless.

---

## Test Strategy

`tests/envmon/test_qc_sample_summary.py` — arcpy-free:

1. `classify_qc_rows` correctly assigns `qc_type` from SampleType field
2. SampleID suffix inference: `-MB` → `method_blank`, `-MS` → `matrix_spike`
3. Blank with detected value → WARNING in QA, `blank_detections` count
4. `compute_rpd(10.0, 8.0)` == approx 22.22
5. RPD > threshold → `pass_fail = "fail"`, `duplicate_failures` count
6. `write_qc_summary_workbook` produces xlsx with one sheet per QC type present
7. Summary sheet present in workbook
8. Primary samples excluded from QC sheets
