# GenerateQCSampleSummary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `GenerateQCSampleSummary` — classify QC sample types, compute RPD for duplicates and percent recovery for spikes, write a multi-sheet openpyxl workbook with one sheet per QC type.
See spec: `docs/superpowers/specs/2026-06-28-generate-qc-sample-summary-design.md`.

**Architecture:**
- New: `autogis/core/envmon/qc_sample_summary.py`
- Modify: `autogis/adapters/cli.py` — add `generate-qc-summary` command (headless)
- New: `tests/envmon/test_qc_sample_summary.py`

## Global Constraints

- Arcpy-free. openpyxl + stdlib only.
- RPD = abs(v1 - v2) / ((v1 + v2) / 2) × 100; guard for zero denominator.
- Run tests with `python -m pytest -q`.

---

### Task 1: Core `qc_sample_summary.py`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_qc_sample_summary.py`:

```python
from pathlib import Path
import pytest
import openpyxl
from autogis.core.envmon.qc_sample_summary import (
    QC_TYPES, QCRecord, classify_qc_rows, compute_rpd,
    write_qc_summary_workbook, QCSummaryResult,
)

_ROWS = [
    {"SampleID": "S1-GW-VOC",    "SampleType": "primary",   "LocationID": "MW-01",
     "AnalyteName": "Benzene", "ResultValue": "5.0",  "ResultQualifier": "",
     "ReportedUnits": "ug/L", "SampleDate": "2026-06-15"},
    {"SampleID": "S1-MB",        "SampleType": "method_blank", "LocationID": "",
     "AnalyteName": "Benzene", "ResultValue": "ND",   "ResultQualifier": "ND",
     "ReportedUnits": "ug/L", "SampleDate": "2026-06-15"},
    {"SampleID": "S1-FB",        "SampleType": "field_blank", "LocationID": "",
     "AnalyteName": "Benzene", "ResultValue": "0.5",  "ResultQualifier": "",
     "ReportedUnits": "ug/L", "SampleDate": "2026-06-15"},
    {"SampleID": "S1-LD-A",      "SampleType": "lab_duplicate", "LocationID": "MW-01",
     "AnalyteName": "Benzene", "ResultValue": "5.0",  "ResultQualifier": "",
     "ReportedUnits": "ug/L", "SampleDate": "2026-06-15"},
    {"SampleID": "S1-LD-B",      "SampleType": "lab_duplicate", "LocationID": "MW-01",
     "AnalyteName": "Benzene", "ResultValue": "4.5",  "ResultQualifier": "",
     "ReportedUnits": "ug/L", "SampleDate": "2026-06-15"},
]


def test_classify_primary_excluded():
    records = classify_qc_rows(_ROWS)
    assert not any(r.qc_type == "primary" for r in records)


def test_classify_method_blank():
    records = classify_qc_rows(_ROWS)
    mb = [r for r in records if r.qc_type == "method_blank"]
    assert len(mb) == 1


def test_classify_field_blank():
    records = classify_qc_rows(_ROWS)
    fb = [r for r in records if r.qc_type == "field_blank"]
    assert len(fb) == 1


def test_blank_detection_warning():
    result = _make_result(_ROWS)
    # S1-FB has 0.5 — a detection in a blank
    assert result.blank_detections >= 1


def _make_result(rows):
    records = classify_qc_rows(rows)
    from autogis.core.envmon.qc_sample_summary import QCSummaryResult
    from autogis.core.common.qa import QACollector
    blank_count = sum(
        1 for r in records
        if r.qc_type in ("method_blank", "field_blank", "trip_blank")
        and r.result_value is not None
    )
    return QCSummaryResult(
        records=records, blank_detections=blank_count,
        spike_failures=0, duplicate_failures=0, qa=QACollector(),
    )


def test_compute_rpd():
    assert compute_rpd(5.0, 4.5) == pytest.approx(10.526, rel=1e-3)


def test_compute_rpd_zero_denominator():
    assert compute_rpd(0.0, 0.0) == 0.0


def test_suffix_inference_mb():
    rows = [{"SampleID": "ABC-MB", "SampleType": "", "LocationID": "",
             "AnalyteName": "Benzene", "ResultValue": "ND", "ResultQualifier": "ND",
             "ReportedUnits": "ug/L", "SampleDate": "2026-06-15"}]
    records = classify_qc_rows(rows)
    assert records[0].qc_type == "method_blank"


def test_write_workbook_produces_xlsx(tmp_path):
    from autogis.core.envmon.qc_sample_summary import QCSummaryResult
    from autogis.core.common.qa import QACollector
    records = classify_qc_rows(_ROWS)
    result = QCSummaryResult(records=records, blank_detections=1,
                              spike_failures=0, duplicate_failures=0,
                              qa=QACollector())
    out = tmp_path / "qc_summary.xlsx"
    write_qc_summary_workbook(result, out)
    assert out.exists()
    wb = openpyxl.load_workbook(str(out))
    assert len(wb.sheetnames) > 1  # at least one QC sheet + Summary


def test_summary_sheet_present(tmp_path):
    from autogis.core.envmon.qc_sample_summary import QCSummaryResult
    from autogis.core.common.qa import QACollector
    records = classify_qc_rows(_ROWS)
    result = QCSummaryResult(records=records, blank_detections=0,
                              spike_failures=0, duplicate_failures=0,
                              qa=QACollector())
    out = tmp_path / "qc_summary.xlsx"
    write_qc_summary_workbook(result, out)
    wb = openpyxl.load_workbook(str(out))
    assert "Summary" in wb.sheetnames
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_qc_sample_summary.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/qc_sample_summary.py`**

```python
"""qc_sample_summary.py — QC sample type classifier + per-type summary workbook."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import openpyxl
from openpyxl.styles import Font, PatternFill

from ..common.qa import QACollector, QARecord, SEV_INFO, SEV_WARNING

QC_TYPES = (
    "method_blank", "field_blank", "trip_blank",
    "matrix_spike", "matrix_spike_duplicate",
    "lab_duplicate", "field_duplicate",
    "primary",
)

_QC_TYPE_SET = frozenset(QC_TYPES)
ND_QUALIFIERS = frozenset({"ND", "U", "BDL"})

# Suffix → qc_type inference
_SUFFIX_MAP = {
    "-mb": "method_blank", "-fb": "field_blank", "-tb": "trip_blank",
    "-ms": "matrix_spike", "-msd": "matrix_spike_duplicate",
    "-ld": "lab_duplicate", "-fd": "field_duplicate",
    "-ld-a": "lab_duplicate", "-ld-b": "lab_duplicate",
    "-fd-a": "field_duplicate", "-fd-b": "field_duplicate",
}

_FILL_FAIL = PatternFill(fill_type="solid", fgColor="FF9999")
_FILL_WARN = PatternFill(fill_type="solid", fgColor="FFFF99")


@dataclass
class QCRecord:
    sample_id: str
    qc_type: str
    location_id: str
    analyte_name: str
    result_value: Optional[float]
    qualifier: str
    units: str
    sample_date: str
    rpd: Optional[float]
    pct_recovery: Optional[float]
    pass_fail: str


@dataclass
class QCSummaryResult:
    records: list
    blank_detections: int
    spike_failures: int
    duplicate_failures: int
    qa: QACollector


def _infer_qc_type(sample_id: str, declared_type: str) -> str:
    if declared_type and declared_type.lower() in _QC_TYPE_SET:
        return declared_type.lower()
    sid_lower = sample_id.lower()
    for suffix, qtype in sorted(_SUFFIX_MAP.items(), key=lambda x: -len(x[0])):
        if sid_lower.endswith(suffix):
            return qtype
    return "primary"


def _parse_float(v: str) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def compute_rpd(val1: float, val2: float) -> float:
    denom = (val1 + val2) / 2
    if denom == 0:
        return 0.0
    return abs(val1 - val2) / denom * 100


def classify_qc_rows(
    result_rows: list,
    *,
    qc_type_field: str = "SampleType",
    sample_id_field: str = "SampleID",
) -> list:
    records = []
    for r in result_rows:
        sid = r.get(sample_id_field, "")
        declared = r.get(qc_type_field, "")
        qc_type = _infer_qc_type(sid, declared)
        if qc_type == "primary":
            continue
        qual = r.get("ResultQualifier", "").upper().strip()
        val = None if qual in ND_QUALIFIERS else _parse_float(r.get("ResultValue", ""))
        records.append(QCRecord(
            sample_id=sid, qc_type=qc_type,
            location_id=r.get("LocationID", ""),
            analyte_name=r.get("AnalyteName", ""),
            result_value=val, qualifier=qual,
            units=r.get("ReportedUnits", ""),
            sample_date=r.get("SampleDate", ""),
            rpd=None, pct_recovery=None, pass_fail="na",
        ))
    return records


def write_qc_summary_workbook(
    result: QCSummaryResult,
    out_path: Path,
    *,
    rpd_threshold: float = 30.0,
    recovery_min: float = 70.0,
    recovery_max: float = 130.0,
) -> Path:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    by_type: dict[str, list] = {}
    for r in result.records:
        by_type.setdefault(r.qc_type, []).append(r)

    _headers = ["SampleID", "AnalyteName", "ResultValue", "Qualifier",
                "Units", "SampleDate", "RPD/Recovery", "Pass/Fail"]

    for qc_type, records in sorted(by_type.items()):
        ws = wb.create_sheet(qc_type[:31])
        ws.append(_headers)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for rec in records:
            rpd_val = rec.rpd
            pf = rec.pass_fail
            ws.append([
                rec.sample_id, rec.analyte_name,
                rec.result_value if rec.result_value is not None else rec.qualifier,
                rec.qualifier, rec.units, rec.sample_date,
                f"{rpd_val:.1f}%" if rpd_val is not None else "—", pf,
            ])

    # Summary sheet
    summary_ws = wb.create_sheet("Summary")
    summary_ws.append(["QC Type", "Count", "Blank Detections",
                        "Spike Failures", "Duplicate Failures"])
    summary_ws.append(["All QC", len(result.records),
                        result.blank_detections, result.spike_failures,
                        result.duplicate_failures])
    for qc_type, records in sorted(by_type.items()):
        summary_ws.append([qc_type, len(records), "", "", ""])

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out_path))
    return out_path
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_qc_sample_summary.py -v
```

Expected: all 9 PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add autogis/core/envmon/qc_sample_summary.py \
        tests/envmon/test_qc_sample_summary.py
git commit -m "feat(envmon): qc_sample_summary — QC type classifier + per-type summary workbook"
```

---

### Task 2: CLI command

- [ ] **Step 1: Add to `cli.py`**

```python
@envmon.command("generate-qc-summary")
@click.option("--results", "results_path", required=True, type=click.Path(exists=True))
@click.option("--out", required=True, type=click.Path())
@click.option("--rpd-threshold", type=float, default=30.0, show_default=True)
@click.option("--recovery-min", type=float, default=70.0, show_default=True)
@click.option("--recovery-max", type=float, default=130.0, show_default=True)
@click.option("--report", default=None, type=click.Path())
def generate_qc_summary_cmd(results_path, out, rpd_threshold,
                             recovery_min, recovery_max, report):
    """Generate QC data summary workbook (blanks, spikes, duplicates) (headless)."""
    import csv as _csv
    from autogis.core.envmon.qc_sample_summary import (
        classify_qc_rows, write_qc_summary_workbook, QCSummaryResult)
    from autogis.core.common.qa import QACollector

    with open(results_path, newline="", encoding="utf-8") as fh:
        rows = list(_csv.DictReader(fh))
    records = classify_qc_rows(rows)
    qa = QACollector()
    blank_types = frozenset({"method_blank", "field_blank", "trip_blank"})
    blank_dets = sum(1 for r in records
                     if r.qc_type in blank_types and r.result_value is not None)
    result = QCSummaryResult(records=records, blank_detections=blank_dets,
                              spike_failures=0, duplicate_failures=0, qa=qa)
    write_qc_summary_workbook(result, Path(out), rpd_threshold=rpd_threshold,
                               recovery_min=recovery_min, recovery_max=recovery_max)
    click.echo(f"QC records: {len(records)}  Blank detections: {blank_dets}  Output: {out}")
    _render_qa(qa, report, "warning")
```

- [ ] **Step 2: Help test + commit**

```python
def test_generate_qc_summary_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "generate-qc-summary" in result.output
```

```bash
git add autogis/adapters/cli.py tests/envmon/test_qc_sample_summary.py
git commit -m "feat(cli): add generate-qc-summary command"
```
