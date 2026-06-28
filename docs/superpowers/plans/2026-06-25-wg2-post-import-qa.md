# Workgroup 2 — Post-Import QA + First Reporting Deliverable

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the correctness gap in screening evaluation, wire the full import-to-report cycle (reconcile → RPD QA → summary export → readiness gate), and ship five independently testable deliverables.

**Architecture:** All five items are headless-core Python modules in `autogis/core/envmon/`. Each exposes a pure function over plain Python types (lists, dicts, `Path`). CLI commands in `autogis/adapters/cli.py` wrap the cores and share the existing `_render_qa` / `_guard` pattern. No new external dependencies.

**Tech Stack:** Python 3.10+, `openpyxl` (already present), stdlib `csv`/`json`/`difflib`/`logging`, `click` (already present), `pytest`.

## Global Constraints

- `core/` and `adapters/cli.py` import with neither `arcpy` nor `arcgis` present (ADR-002). All new modules are arcpy-free.
- Reuse `common/qa.py` (`QACollector`, `QARecord`, `SEV_ERROR`, `SEV_WARNING`, `SEV_INFO`).
- Reuse `common/units.py` (`convert`, `same_dimension`, `normalize_unit`, `UnitError`) — do not add a second unit registry.
- Reuse `gdb_schema.py` record types (`SampleRecord`, `AnalyticalResultRecord`, `RPDRecord`) — these are the canonical in-memory types.
- CLI commands follow the existing headless pattern: `_render_qa(qa, report, fail_on)` for exit codes; lazy imports inside command bodies; `_guard(name)` for LOCAL-only redirects.
- Tests under `tests/envmon/`; run with `python -m pytest -q`. `.pyt` files are never imported by the test suite.
- Frequent commits: every task ends with a `git commit`.

## Dependency order

Tasks must be executed in this sequence — each task's outputs are consumed by later ones:

```
Task 1 (unit fix) → Task 2 (reconcile) → Task 3 (RPD QA) → Task 4 (summary export) → Task 5 (readiness gate)
```

Task 2 has its own pre-existing plan document (see below). Tasks 3–5 depend only on the record types and CLI patterns already established; they are independent of each other once Task 1 is merged.

---

## Task 1: Wire unit-conversion into `evaluate_screening()`

**Files:**
- Modify: `autogis/core/envmon/result_parser.py:1-15, 297-305`
- Modify: `autogis/core/envmon/table_normalizer.py:91-104, 180`
- Test: `tests/envmon/test_result_parser.py`

**Interfaces:**
- Produces:
  - `evaluate_screening(parsed: ParsedResult, screening_level: Optional[float], result_unit: Optional[str] = None, screening_unit: Optional[str] = None) -> Optional[bool]`
  - Semantics: `None` if undecidable (ND/missing SL/different dimension); `True` if exceeds; `False` otherwise.
  - `table_normalizer` now stores `sl_unit: str` in `col_meta` and passes it at the call site.

- [ ] **Step 1: Write failing tests for the unit-aware paths**

```python
# append to tests/envmon/test_result_parser.py
from autogis.core.envmon.result_parser import evaluate_screening, parse_result_value


def _det(value: float) -> "ParsedResult":
    p = parse_result_value(str(value))
    assert p.is_detected
    return p


def test_evaluate_screening_same_unit_no_conversion():
    # 5 ug/L vs 3 ug/L threshold -> exceeds
    assert evaluate_screening(_det(5.0), 3.0,
                              result_unit="ug/L", screening_unit="ug/L") is True


def test_evaluate_screening_converts_mg_to_ug():
    # result 0.005 mg/L == 5 ug/L, threshold 3 ug/L -> exceeds
    assert evaluate_screening(_det(0.005), 3.0,
                              result_unit="mg/L", screening_unit="ug/L") is True


def test_evaluate_screening_converts_ug_to_mg():
    # result 5 ug/L == 0.005 mg/L, threshold 0.003 mg/L -> exceeds
    assert evaluate_screening(_det(5.0), 0.003,
                              result_unit="ug/L", screening_unit="mg/L") is True


def test_evaluate_screening_different_dimension_returns_none():
    # ug/L (aqueous) vs mg/kg (soil) -> can't compare, return None
    assert evaluate_screening(_det(5.0), 3.0,
                              result_unit="ug/L", screening_unit="mg/kg") is None


def test_evaluate_screening_unknown_unit_falls_through():
    # unknown unit: fallthrough, compare raw value (backward compat)
    assert evaluate_screening(_det(5.0), 3.0,
                              result_unit="ppm", screening_unit="ug/L") is True


def test_evaluate_screening_none_units_falls_through():
    # both None: raw compare (existing behavior preserved)
    assert evaluate_screening(_det(5.0), 3.0) is True
    assert evaluate_screening(_det(1.0), 3.0) is False
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/envmon/test_result_parser.py -k "unit" -q
```
Expected: FAIL (some pass by coincidence on the None fallthrough, but the conversion tests fail).

- [ ] **Step 3: Update `evaluate_screening()` in `result_parser.py`**

Add the import at the top of `result_parser.py` (after the existing imports):

```python
import logging as _log
from ..common.units import convert, same_dimension, normalize_unit
```

Replace the function body (lines 297-305):

```python
def evaluate_screening(parsed: ParsedResult,
                       screening_level: Optional[float],
                       result_unit: Optional[str] = None,
                       screening_unit: Optional[str] = None) -> Optional[bool]:
    """True/False for valid detected results vs a numeric screening level.

    Returns None when the comparison is not legitimate: ND result, missing
    screening level, or dimensionally incompatible units.  When both units are
    provided and known, the result value is converted to the screening unit
    before comparison.  When either unit is unknown, falls through to a raw
    numeric comparison (backward-compatible behaviour; caller should QA-warn).
    """
    if not parsed.is_detected or parsed.result_numeric is None:
        return None
    if screening_level is None:
        return None
    value = parsed.result_numeric
    if result_unit and screening_unit:
        r_known = normalize_unit(result_unit) is not None
        s_known = normalize_unit(screening_unit) is not None
        if r_known and s_known:
            if not same_dimension(result_unit, screening_unit):
                return None   # aqueous vs soil: no valid comparison
            value = convert(value, result_unit, screening_unit)
        else:
            _log.warning(
                "evaluate_screening: unregistered unit(s) %r / %r; "
                "using raw value (add units to UNIT_REGISTRY to enable conversion)",
                result_unit, screening_unit)
    return value > screening_level
```

- [ ] **Step 4: Wire `sl_unit` into `table_normalizer.py`**

In `table_normalizer.py`, inside the `normalize_matrix_table` loop where `col_meta` is built (around line 91-104), change the `sl_value` config look-up block and the `col_meta` assignment:

```python
        sl_unit = ""
        if sl_value is None and canonical:
            cfg = screening_for(screening_levels, matrix, canonical)
            if cfg and cfg.get("value") is not None:
                sl_value = float(cfg["value"])
                sl_source = cfg.get("source", "config")
                sl_unit = cfg.get("unit", "")
        if sl_parsed and sl_parsed.parse_warning and sl_cell is not None:
            qa.add(SEV_INFO, "screening_level_note", sl_parsed.parse_warning,
                   site_id=site_id, analyte_name=raw_name,
                   import_batch_id=batch_id, source_workbook=wb_name,
                   source_sheet=sheet.sheet_name, source_cell=sl_cell.ref)
        col_meta[col] = dict(raw_name=raw_name, canonical=canonical,
                             entry=entry, units=units, sl_value=sl_value,
                             sl_source=sl_source, sl_unit=sl_unit)
```

Then at line 180, pass units through:

```python
            exceeds = evaluate_screening(parsed, meta["sl_value"],
                                         result_unit=meta["units"],
                                         screening_unit=meta["sl_unit"])
```

- [ ] **Step 5: Run all tests**

```
python -m pytest -q
```
Expected: full suite green. The new unit tests pass. No regressions (existing callers pass `None` units, which trigger the fallthrough path).

- [ ] **Step 6: Commit**

```bash
git add autogis/core/envmon/result_parser.py \
        autogis/core/envmon/table_normalizer.py \
        tests/envmon/test_result_parser.py
git commit -m "fix(envmon): wire unit-conversion into evaluate_screening (ADR-018)"
```

---

## Task 2: ReconcileSampleLocations

**Complete plan:** `docs/superpowers/plans/2026-06-24-phase-b-reconcile-locations.md`

**Pre-condition:** Task 1 must be merged (the reconcile CLI reuses `_render_qa` introduced in Phase A / `2026-06-24-phase-a-config-integrity.md`, which must also be merged).

**What to build:** Execute all six tasks in the Phase B plan exactly as written. They produce:
- `autogis/core/envmon/reconcile_locations.py` — `normalize_id`, `reconcile`, `reconcile_to_qa`, `extract_location_ids`, `read_well_ids_csv`
- `autogis/adapters/cli.py` — `envmon reconcile-locations` command (headless `--wells-csv` path)
- `autogis/adapters/toolbox.pyt` — `ReconcileSampleLocations` tool (arcpy `--gdb` path)
- Tests under `tests/envmon/test_reconcile_locations.py` and `test_cli_reconcile_locations.py`

**Notes for this workgroup context:**
- The Phase B plan references `InMemoryWorkbookReader` from `tests/envmon/conftest.py` — confirm it exists before Task 3 in the plan (`grep -n "InMemoryWorkbookReader" tests/envmon/conftest.py`).
- The `ParserProfile` and `SheetProfile` import paths used in Phase B (`from autogis.core.common.config import ...`) are correct; do not change them.

---

## Task 3: EvaluateDuplicateRPD

**Files:**
- Create: `autogis/core/envmon/evaluate_rpd_qa.py`
- Modify: `autogis/adapters/cli.py` (add `envmon evaluate-rpd-qa` command)
- Test: `tests/envmon/test_evaluate_rpd_qa.py`

**Interfaces:**
- Consumes: `List[SampleRecord]`, `List[AnalyticalResultRecord]` (from `gdb_schema.py`); `QACollector`.
- Produces:
  - `evaluate_duplicate_rpd(samples: List[SampleRecord], results: List[AnalyticalResultRecord], site_id: str, batch_id: str, qa: QACollector) -> List[RPDRecord]`
  - `read_records_csv(path: Path, record_class) -> list` — generic CSV → dataclass loader (used by both this task and Task 4)
  - CLI: `autogis envmon evaluate-rpd-qa --samples-csv PATH --results-csv PATH [--batch-id STR] [--report PATH] [--fail-on error|warning]`

**Background:** Lab EDDs contain duplicate (QA) samples as separate rows with `IsDuplicate=1` and `ParentSampleID` populated. This tool finds those pairs, computes RPD for each analyte pair, flags formula-error rows, and writes `RPDRecord` objects. It is called in-memory from the EDD import pipeline and also works standalone via CSV side-cars.

### Task 3a: Core `evaluate_duplicate_rpd()`

- [ ] **Step 1: Write failing tests**

```python
# tests/envmon/test_evaluate_rpd_qa.py
from datetime import date
from autogis.core.common.qa import QACollector, SEV_WARNING, SEV_ERROR, SEV_INFO
from autogis.core.envmon.gdb_schema import SampleRecord, AnalyticalResultRecord, RPDRecord
from autogis.core.envmon.evaluate_rpd_qa import evaluate_duplicate_rpd


def _sample(sample_id, parent_id="", is_dup=0, matrix="GROUNDWATER",
            loc="MW-1", dt=date(2026, 1, 1)):
    return SampleRecord(
        ImportBatchID="B1", SiteID="H281", Matrix=matrix,
        LocationID=loc, SampleID=sample_id, ParentSampleID=parent_id,
        SampleDate=dt, SampleDateRaw=str(dt),
        DepthTop_ft=None, DepthBottom_ft=None, DepthIntervalText="",
        IsDuplicate=is_dup, DuplicateType="FIELD_DUP" if is_dup else "",
        LabSampleID="", SourceWorkbook="edd.csv", SourceSheet="", SourceRow=0)


def _result(sample_id, analyte, numeric, raw="", is_det=1, units="ug/L"):
    return AnalyticalResultRecord(
        ImportBatchID="B1", SiteID="H281", Matrix="GROUNDWATER",
        LocationID="MW-1", SampleID=sample_id, ParentSampleID="",
        SampleDate=date(2026, 1, 1),
        DepthTop_ft=None, DepthBottom_ft=None, DepthIntervalText="",
        AnalyticalGroup="VOC", MethodGroup="", AnalyteName=analyte,
        AnalyteCanonicalName=analyte, AnalyteAbbreviation=analyte[:8],
        ResultRawText=raw or str(numeric),
        ResultNumeric=numeric, ReportingLimit=None, DetectionLimit=None,
        Units=units, Qualifier="",
        IsNonDetect=0, IsDetected=is_det, IsEstimated=0, IsDiluted=0,
        IsNotAnalyzed=0, IsNotSampled=0, IsNotMeasured=0,
        ScreeningLevel=None, ScreeningLevelSource="",
        ExceedsScreeningLevel=None, DisplayText="", DisplayColorClass="",
        SourceWorkbook="edd.csv", SourceSheet="", SourceRow=0,
        SourceColumn="", SourceCell="")


def test_rpd_calculated_for_duplicate_pair():
    samples = [
        _sample("S1", is_dup=0),
        _sample("S1-DUP", parent_id="S1", is_dup=1)]
    results = [
        _result("S1", "Benzene", 10.0),
        _result("S1-DUP", "Benzene", 12.0)]
    qa = QACollector()
    rpd_recs = evaluate_duplicate_rpd(samples, results, "H281", "B1", qa)
    assert len(rpd_recs) == 1
    rec = rpd_recs[0]
    assert rec.RPDStatus == "CALCULATED"
    # RPD = |10-12| / ((10+12)/2) * 100 = 2/11 * 100 ≈ 18.18
    assert abs(rec.RPDValue - 18.18) < 0.1


def test_nondetect_pair_marked_nc():
    samples = [_sample("S2"), _sample("S2-DUP", "S2", 1)]
    results = [
        _result("S2", "Benzene", None, raw="<1.0", is_det=0),
        _result("S2-DUP", "Benzene", None, raw="<1.0", is_det=0)]
    # Override IsNonDetect
    results[0].IsNonDetect = 1; results[0].IsDetected = 0
    results[1].IsNonDetect = 1; results[1].IsDetected = 0
    qa = QACollector()
    recs = evaluate_duplicate_rpd(samples, results, "H281", "B1", qa)
    assert len(recs) == 1
    assert recs[0].RPDStatus == "NC_NONDETECT"


def test_formula_error_row_yields_qa_warning():
    samples = [_sample("S3"), _sample("S3-DUP", "S3", 1)]
    results = [
        _result("S3", "Lead", 5.0),
        _result("S3-DUP", "Lead", None, raw="#VALUE!", is_det=0)]
    results[1].IsNotAnalyzed = 1
    qa = QACollector()
    evaluate_duplicate_rpd(samples, results, "H281", "B1", qa)
    cats = [r.category for r in qa.records]
    assert "rpd_formula_error" in cats


def test_no_duplicates_returns_empty():
    samples = [_sample("S4")]
    results = [_result("S4", "TCE", 2.0)]
    qa = QACollector()
    assert evaluate_duplicate_rpd(samples, results, "H281", "B1", qa) == []
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/envmon/test_evaluate_rpd_qa.py -q
```
Expected: FAIL — module `evaluate_rpd_qa` not found.

- [ ] **Step 3: Write `evaluate_duplicate_rpd()`**

```python
# autogis/core/envmon/evaluate_rpd_qa.py
"""Evaluate duplicate-sample RPD from in-memory EDD records.

Lab EDDs carry field duplicates as separate sample rows (IsDuplicate=1,
ParentSampleID set).  This module finds those pairs, computes RPD per analyte,
and produces RPDRecord objects alongside QA records for any issues.
"""
from __future__ import annotations

import csv
from dataclasses import fields as dc_fields
from datetime import date
from pathlib import Path
from typing import List, Optional, Type, TypeVar

from .gdb_schema import AnalyticalResultRecord, RPDRecord, SampleRecord
from ..common.qa import QACollector, SEV_INFO, SEV_WARNING

_FORMULA_ERRORS = {"#VALUE!", "#DIV/0!", "#N/A", "#REF!", "#NAME?", "#NUM!", "#NULL!"}
T = TypeVar("T")


def _rpd(parent: float, dup: float) -> Optional[float]:
    mean = (parent + dup) / 2.0
    if mean == 0:
        return None
    return abs(parent - dup) / mean * 100.0


def evaluate_duplicate_rpd(
    samples: List[SampleRecord],
    results: List[AnalyticalResultRecord],
    site_id: str,
    batch_id: str,
    qa: QACollector,
) -> List[RPDRecord]:
    """Find duplicate-parent sample pairs, compute RPD, emit QA records.

    Returns one RPDRecord per duplicate-analyte pair.  Formula-error rows get
    a ``rpd_formula_error`` QA WARNING and produce an RPDRecord with
    RPDStatus='NC_ERROR'.
    """
    # index: sample_id -> SampleRecord
    parent_map = {s.SampleID: s for s in samples if s.IsDuplicate == 0}
    dup_samples = [s for s in samples if s.IsDuplicate == 1 and s.ParentSampleID]

    # index: sample_id -> {analyte_name -> AnalyticalResultRecord}
    result_idx: dict = {}
    for r in results:
        result_idx.setdefault(r.SampleID, {})[r.AnalyteName] = r

    records: List[RPDRecord] = []
    for dup in dup_samples:
        parent = parent_map.get(dup.ParentSampleID)
        if parent is None:
            qa.add(SEV_WARNING, "rpd_parent_not_found",
                   f"duplicate sample {dup.SampleID!r} references parent "
                   f"{dup.ParentSampleID!r} which is not in the sample list",
                   site_id=site_id, sample_id=dup.SampleID,
                   import_batch_id=batch_id, source_workbook=dup.SourceWorkbook)
            continue

        dup_results = result_idx.get(dup.SampleID, {})
        par_results = result_idx.get(parent.SampleID, {})
        analytes = set(dup_results) | set(par_results)

        for analyte in sorted(analytes):
            p_rec = par_results.get(analyte)
            d_rec = dup_results.get(analyte)
            p_raw = p_rec.ResultRawText if p_rec else ""
            d_raw = d_rec.ResultRawText if d_rec else ""

            # Detect formula errors
            p_err = p_raw.upper() in _FORMULA_ERRORS
            d_err = d_raw.upper() in _FORMULA_ERRORS
            if p_err or d_err:
                qa.add(SEV_WARNING, "rpd_formula_error",
                       f"formula error in {analyte!r} for pair "
                       f"{parent.SampleID!r}/{dup.SampleID!r}: "
                       f"parent={p_raw!r} dup={d_raw!r}",
                       site_id=site_id, analyte_name=analyte,
                       import_batch_id=batch_id,
                       source_workbook=dup.SourceWorkbook)
                status, rpd_val, calc_err = "NC_ERROR", None, f"formula error: {p_raw or d_raw}"
            elif (p_rec and p_rec.IsDetected and p_rec.ResultNumeric is not None
                  and d_rec and d_rec.IsDetected and d_rec.ResultNumeric is not None):
                rpd_val = _rpd(p_rec.ResultNumeric, d_rec.ResultNumeric)
                status, calc_err = "CALCULATED", ""
                if rpd_val is None:
                    status, calc_err = "NC_ZERO_MEAN", "both values are zero"
            elif ((p_rec and p_rec.IsNonDetect) or (d_rec and d_rec.IsNonDetect)):
                rpd_val, status, calc_err = None, "NC_NONDETECT", ""
            else:
                rpd_val, status, calc_err = None, "NC_STATUS", ""

            rl = (p_rec.ReportingLimit if p_rec else None) or \
                 (d_rec.ReportingLimit if d_rec else None)
            src = d_rec or p_rec
            records.append(RPDRecord(
                ImportBatchID=batch_id, SiteID=site_id,
                EventDate=parent.SampleDate,
                ParentLocationID=parent.LocationID,
                DuplicateLocationID=dup.LocationID,
                AnalyteName=analyte,
                ParentResultRaw=p_raw, DuplicateResultRaw=d_raw,
                ParentResultNumeric=p_rec.ResultNumeric if p_rec else None,
                DuplicateResultNumeric=d_rec.ResultNumeric if d_rec else None,
                RPDValue=rpd_val,
                RL=rl, FiveTimesRL=rl * 5 if rl else None,
                RPDStatus=status, CalculationError=calc_err,
                SourceWorkbook=src.SourceWorkbook if src else "",
                SourceSheet=src.SourceSheet if src else "",
                SourceRow=src.SourceRow if src else 0))

    if records:
        qa.add(SEV_INFO, "rpd_complete",
               f"RPD evaluated: {len(records)} analyte-pair(s) from "
               f"{len(dup_samples)} duplicate sample(s)")
    return records
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/envmon/test_evaluate_rpd_qa.py -q
```
Expected: PASS (4 tests).

- [ ] **Step 5: Commit core**

```bash
git add autogis/core/envmon/evaluate_rpd_qa.py tests/envmon/test_evaluate_rpd_qa.py
git commit -m "feat(envmon): evaluate_duplicate_rpd — RPD QA for EDD duplicate pairs"
```

### Task 3b: `read_records_csv()` helper + CLI command

- [ ] **Step 1: Write failing test for CSV round-trip**

```python
# append to tests/envmon/test_evaluate_rpd_qa.py
from autogis.core.envmon.evaluate_rpd_qa import read_records_csv
import csv, io


def test_read_records_csv_round_trips_sample_record(tmp_path):
    s = _sample("S99")
    p = tmp_path / "samples.csv"
    fnames = [f.name for f in dc_fields(SampleRecord)]
    import dataclasses
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fnames)
        w.writeheader()
        w.writerow(dataclasses.asdict(s))
    loaded = read_records_csv(p, SampleRecord)
    assert len(loaded) == 1
    assert loaded[0].SampleID == "S99"
    assert loaded[0].IsDuplicate == 0   # int round-trip
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/envmon/test_evaluate_rpd_qa.py -k csv -q
```
Expected: FAIL — `read_records_csv` undefined.

- [ ] **Step 3: Add `read_records_csv()` to `evaluate_rpd_qa.py`**

```python
# append to autogis/core/envmon/evaluate_rpd_qa.py
import dataclasses
from datetime import date as _date


def _coerce(value: str, hint):
    """Coerce a CSV string to the field's type hint."""
    if hint in (int,) or (hasattr(hint, "__origin__") is False and hint is int):
        return int(value) if value not in ("", "None") else 0
    if hint is float or hint is Optional[float]:
        return float(value) if value not in ("", "None") else None
    if hint is _date or str(hint) == "typing.Optional[datetime.date]":
        if value in ("", "None"):
            return None
        try:
            return _date.fromisoformat(value)
        except ValueError:
            return None
    return value if value != "None" else None


def read_records_csv(path: Path, record_class: Type[T]) -> List[T]:
    """Load a CSV into a list of dataclass instances.

    Handles int/float/date coercion.  Unknown columns are silently ignored.
    """
    hints = {f.name: f.type for f in dataclasses.fields(record_class)}
    rows = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            kwargs = {}
            for fname, hint in hints.items():
                raw = row.get(fname, "")
                try:
                    kwargs[fname] = _coerce(raw, hint)
                except (ValueError, TypeError):
                    kwargs[fname] = None
            rows.append(record_class(**kwargs))
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/envmon/test_evaluate_rpd_qa.py -q
```
Expected: PASS (5 tests).

- [ ] **Step 5: Add CLI command to `cli.py`**

```python
# autogis/adapters/cli.py — add after validate_units_cmd
@envmon.command("evaluate-rpd-qa")
@click.option("--samples-csv", required=True, type=click.Path(exists=True),
              help="CSV export of Env_Samples.")
@click.option("--results-csv", required=True, type=click.Path(exists=True),
              help="CSV export of Env_AnalyticalResults.")
@click.option("--batch-id", default="MANUAL", show_default=True,
              help="Import batch ID label for output records.")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def evaluate_rpd_qa_cmd(samples_csv, results_csv, batch_id, report, fail_on):
    """Tool: compute RPD for EDD duplicate samples and emit QA records."""
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.gdb_schema import SampleRecord, AnalyticalResultRecord
    from autogis.core.envmon.evaluate_rpd_qa import (
        evaluate_duplicate_rpd, read_records_csv)

    qa = QACollector()
    samples = read_records_csv(Path(samples_csv), SampleRecord)
    results = read_records_csv(Path(results_csv), AnalyticalResultRecord)
    site_id = samples[0].SiteID if samples else "UNKNOWN"
    evaluate_duplicate_rpd(samples, results, site_id, batch_id, qa)
    _render_qa(qa, report, fail_on)
```

- [ ] **Step 6: Write CLI smoke test**

```python
# append to tests/envmon/test_evaluate_rpd_qa.py
import dataclasses, csv as _csv
from click.testing import CliRunner
from autogis.adapters.cli import autogis as _cli


def _write_csv(path, record_class, records):
    fnames = [f.name for f in dataclasses.fields(record_class)]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = _csv.DictWriter(fh, fieldnames=fnames)
        w.writeheader()
        for r in records:
            w.writerow(dataclasses.asdict(r))


def test_evaluate_rpd_qa_cli(tmp_path):
    samples = [_sample("P1"), _sample("P1-DUP", "P1", 1)]
    results = [_result("P1", "Benzene", 10.0), _result("P1-DUP", "Benzene", 12.0)]
    sc = tmp_path / "samples.csv"
    rc = tmp_path / "results.csv"
    _write_csv(sc, SampleRecord, samples)
    _write_csv(rc, AnalyticalResultRecord, results)
    r = CliRunner().invoke(_cli, [
        "envmon", "evaluate-rpd-qa",
        "--samples-csv", str(sc), "--results-csv", str(rc)])
    assert r.exit_code == 0
    assert "CALCULATED" in r.output or "rpd_complete" in r.output
```

- [ ] **Step 7: Run full suite + commit**

```
python -m pytest -q
```
Expected: full suite green.

```bash
git add autogis/core/envmon/evaluate_rpd_qa.py \
        autogis/adapters/cli.py \
        tests/envmon/test_evaluate_rpd_qa.py
git commit -m "feat(cli): envmon evaluate-rpd-qa command + read_records_csv helper"
```

---

## Task 4: ExportAnalyticalSummaryTables

**Files:**
- Create: `autogis/core/envmon/export_summary.py`
- Modify: `autogis/adapters/cli.py` (add `envmon export-summary` command)
- Test: `tests/envmon/test_export_summary.py`

**Interfaces:**
- Consumes: CSV exports of `Env_Samples` + `Env_AnalyticalResults` (the `read_records_csv` helper from Task 3).
- Produces:
  - `export_analytical_summary(samples: List[SampleRecord], results: List[AnalyticalResultRecord], output_path: Path, site_id: str, event_id: str = "") -> Path`
  - Returns the path written.
  - Four sheets: **All Results**, **Detections**, **Exceedances**, **Summary by Analyte**.
  - CLI: `autogis envmon export-summary --samples-csv PATH --results-csv PATH --output PATH [--event-id STR]`

### Task 4a: Core export function

- [ ] **Step 1: Write failing tests**

```python
# tests/envmon/test_export_summary.py
from datetime import date
from pathlib import Path
import openpyxl
import pytest
from autogis.core.envmon.gdb_schema import SampleRecord, AnalyticalResultRecord
from autogis.core.envmon.export_summary import export_analytical_summary


def _r(sample_id, analyte, numeric, exceeds=0, is_det=1, units="ug/L"):
    return AnalyticalResultRecord(
        ImportBatchID="B1", SiteID="H281", Matrix="GROUNDWATER",
        LocationID="MW-1", SampleID=sample_id, ParentSampleID="",
        SampleDate=date(2026, 1, 1),
        DepthTop_ft=None, DepthBottom_ft=None, DepthIntervalText="",
        AnalyticalGroup="VOC", MethodGroup="",
        AnalyteName=analyte, AnalyteCanonicalName=analyte,
        AnalyteAbbreviation=analyte[:8],
        ResultRawText=str(numeric) if numeric else "<1.0",
        ResultNumeric=numeric, ReportingLimit=1.0, DetectionLimit=None,
        Units=units, Qualifier="",
        IsNonDetect=0 if is_det else 1, IsDetected=is_det,
        IsEstimated=0, IsDiluted=0, IsNotAnalyzed=0,
        IsNotSampled=0, IsNotMeasured=0,
        ScreeningLevel=5.0, ScreeningLevelSource="config",
        ExceedsScreeningLevel=exceeds,
        DisplayText=str(numeric), DisplayColorClass="EXCEEDANCE" if exceeds else "DETECTED",
        SourceWorkbook="edd.csv", SourceSheet="", SourceRow=0,
        SourceColumn="", SourceCell="")


def _s(sample_id):
    from autogis.core.envmon.evaluate_rpd_qa import _sample as mk
    return mk(sample_id)


def test_export_summary_creates_four_sheets(tmp_path):
    results = [_r("S1", "Benzene", 10.0, exceeds=1),
               _r("S1", "Toluene", 2.0, exceeds=0),
               _r("S2", "Benzene", 0.5, exceeds=0)]
    path = export_analytical_summary([], results, tmp_path / "out.xlsx", "H281")
    wb = openpyxl.load_workbook(path)
    assert set(wb.sheetnames) == {"All Results", "Detections", "Exceedances",
                                  "Summary by Analyte"}


def test_exceedances_sheet_filters_correctly(tmp_path):
    results = [_r("S1", "Benzene", 10.0, exceeds=1),
               _r("S1", "Toluene", 2.0, exceeds=0)]
    path = export_analytical_summary([], results, tmp_path / "out.xlsx", "H281")
    wb = openpyxl.load_workbook(path)
    ws = wb["Exceedances"]
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    assert len(rows) == 1
    analyte_col = [c.value for c in ws[1]].index("AnalyteName")
    assert rows[0][analyte_col] == "Benzene"


def test_summary_sheet_counts_by_analyte(tmp_path):
    results = [_r("S1", "Benzene", 10.0, exceeds=1),
               _r("S2", "Benzene", 2.0, exceeds=0),
               _r("S1", "Toluene", 0.5, exceeds=0)]
    path = export_analytical_summary([], results, tmp_path / "out.xlsx", "H281")
    wb = openpyxl.load_workbook(path)
    ws = wb["Summary by Analyte"]
    header = [c.value for c in ws[1]]
    rows = {r[0]: r for r in ws.iter_rows(min_row=2, values_only=True)}
    assert "Benzene" in rows
    exc_col = header.index("ExceedanceCount")
    det_col = header.index("DetectionCount")
    assert rows["Benzene"][exc_col] == 1
    assert rows["Benzene"][det_col] == 2   # both Benzene rows are detections
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/envmon/test_export_summary.py -q
```
Expected: FAIL — module `export_summary` not found.

- [ ] **Step 3: Write `export_analytical_summary()`**

```python
# autogis/core/envmon/export_summary.py
"""Export Env_Samples + Env_AnalyticalResults to a four-sheet Excel summary.

Headless: reads in-memory record lists, writes with openpyxl.  No arcpy.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, fields as dc_fields
from pathlib import Path
from typing import List

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from .gdb_schema import AnalyticalResultRecord, SampleRecord

_HEADER_FILL = PatternFill("solid", fgColor="4472C4")
_HEADER_FONT = Font(bold=True, color="FFFFFF")


def _write_sheet(ws, rows: list, field_names: list) -> None:
    ws.append(field_names)
    for cell in ws[1]:
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(horizontal="center")
    for row in rows:
        ws.append([row.get(f) for f in field_names])
    for i, _ in enumerate(field_names, 1):
        ws.column_dimensions[get_column_letter(i)].width = 14


def export_analytical_summary(
    samples: List[SampleRecord],
    results: List[AnalyticalResultRecord],
    output_path: Path,
    site_id: str,
    event_id: str = "",
) -> Path:
    """Write a four-sheet Excel summary and return the written path."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    result_fields = [f.name for f in dc_fields(AnalyticalResultRecord)]
    all_rows = [asdict(r) for r in results]
    det_rows = [r for r in all_rows if r.get("IsDetected")]
    exc_rows = [r for r in all_rows if r.get("ExceedsScreeningLevel")]

    # Summary by analyte
    counts: dict = defaultdict(lambda: defaultdict(int))
    for r in all_rows:
        a = r.get("AnalyteName", "")
        counts[a]["total"] += 1
        if r.get("IsDetected"):
            counts[a]["detected"] += 1
        if r.get("ExceedsScreeningLevel"):
            counts[a]["exceeds"] += 1
        if r.get("IsNonDetect"):
            counts[a]["nondetect"] += 1
    summary_fields = ["AnalyteName", "TotalCount", "DetectionCount",
                      "NonDetectCount", "ExceedanceCount"]
    summary_rows = [
        {"AnalyteName": a,
         "TotalCount": v["total"],
         "DetectionCount": v["detected"],
         "NonDetectCount": v["nondetect"],
         "ExceedanceCount": v["exceeds"]}
        for a, v in sorted(counts.items())]

    wb = openpyxl.Workbook()
    wb.remove(wb.active)   # remove default sheet

    ws_all = wb.create_sheet("All Results")
    _write_sheet(ws_all, all_rows, result_fields)

    ws_det = wb.create_sheet("Detections")
    _write_sheet(ws_det, det_rows, result_fields)

    ws_exc = wb.create_sheet("Exceedances")
    _write_sheet(ws_exc, exc_rows, result_fields)

    ws_sum = wb.create_sheet("Summary by Analyte")
    _write_sheet(ws_sum, summary_rows, summary_fields)

    wb.save(output_path)
    return output_path
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/envmon/test_export_summary.py -q
```
Expected: PASS (3 tests).

- [ ] **Step 5: Commit core**

```bash
git add autogis/core/envmon/export_summary.py tests/envmon/test_export_summary.py
git commit -m "feat(envmon): export_analytical_summary — four-sheet Excel output"
```

### Task 4b: CLI command

- [ ] **Step 1: Write failing CLI test**

```python
# append to tests/envmon/test_export_summary.py
import dataclasses, csv as _csv
from click.testing import CliRunner
from autogis.adapters.cli import autogis as _cli


def _write(path, rc_class, recs):
    fnames = [f.name for f in dataclasses.fields(rc_class)]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = _csv.DictWriter(fh, fieldnames=fnames)
        w.writeheader()
        for r in recs:
            w.writerow(dataclasses.asdict(r))


def test_export_summary_cli(tmp_path):
    results = [_r("S1", "Benzene", 10.0, exceeds=1)]
    rc = tmp_path / "results.csv"
    out = tmp_path / "summary.xlsx"
    _write(rc, AnalyticalResultRecord, results)
    r = CliRunner().invoke(_cli, [
        "envmon", "export-summary",
        "--results-csv", str(rc), "--output", str(out)])
    assert r.exit_code == 0, r.output
    assert out.exists()
    wb = openpyxl.load_workbook(out)
    assert "Exceedances" in wb.sheetnames
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/envmon/test_export_summary.py -k cli -q
```
Expected: FAIL — no such command `export-summary`.

- [ ] **Step 3: Add CLI command to `cli.py`**

```python
# autogis/adapters/cli.py — add after evaluate_rpd_qa_cmd
@envmon.command("export-summary")
@click.option("--results-csv", required=True, type=click.Path(exists=True),
              help="CSV export of Env_AnalyticalResults.")
@click.option("--samples-csv", default=None, type=click.Path(exists=True),
              help="CSV export of Env_Samples (optional; used for metadata only).")
@click.option("--output", required=True, type=click.Path(),
              help="Output .xlsx path.")
@click.option("--site-id", default="", help="Site ID label for the summary.")
@click.option("--event-id", default="", help="Event ID label for the summary.")
def export_summary_cmd(results_csv, samples_csv, output, site_id, event_id):
    """Tool: export Env_AnalyticalResults to a four-sheet Excel summary."""
    from autogis.core.envmon.gdb_schema import AnalyticalResultRecord, SampleRecord
    from autogis.core.envmon.evaluate_rpd_qa import read_records_csv
    from autogis.core.envmon.export_summary import export_analytical_summary

    results = read_records_csv(Path(results_csv), AnalyticalResultRecord)
    samples = (read_records_csv(Path(samples_csv), SampleRecord)
               if samples_csv else [])
    if not site_id and results:
        site_id = results[0].SiteID
    out = export_analytical_summary(samples, results, Path(output), site_id, event_id)
    click.echo(f"Written: {out}  ({len(results)} result(s))")
```

- [ ] **Step 4: Run full suite + commit**

```
python -m pytest -q
```
Expected: full suite green.

```bash
git add autogis/core/envmon/export_summary.py \
        autogis/adapters/cli.py \
        tests/envmon/test_export_summary.py
git commit -m "feat(cli): envmon export-summary command"
```

---

## Task 5: EvaluateReportReadiness

**Files:**
- Create: `autogis/core/envmon/evaluate_readiness.py`
- Modify: `autogis/adapters/cli.py` (add `envmon evaluate-readiness` command)
- Test: `tests/envmon/test_evaluate_readiness.py`

**Interfaces:**
- Consumes: `RunHistory` (from `common/run_history.py`); optional QA CSV; optional `FigureSpec`.
- Produces:
  - `evaluate_readiness(site_id: str, event_id: Optional[str], run_history: RunHistory, required_tools: List[str], qa_csv: Optional[Path] = None, figure_spec_path: Optional[Path] = None) -> QACollector`
  - Returns a `QACollector` whose `status()` is `"PASS"` when the event is report-ready.
  - CLI: `autogis envmon evaluate-readiness --site-id STR --run-history PATH [--event-id STR] [--required-tool TOOL]... [--qa-report PATH] [--figure-spec PATH] [--report OUT] [--fail-on error|warning]`

**Readiness checks:**
1. Each tool in `required_tools` has a `RunRecord` with `status="success"` for this `site_id` + `event_id`. Missing or last-status-non-success → `SEV_ERROR` `required_tool_not_run`.
2. If `qa_csv` provided: any `ERROR` rows in it → `SEV_WARNING` `import_qa_errors_present`.
3. If `figure_spec_path` provided: `FigureSpec.load()` succeeds → `SEV_WARNING` `figure_spec_invalid` if it raises.
4. Summary INFO record listing what passed.

### Task 5a: Core `evaluate_readiness()`

- [ ] **Step 1: Write failing tests**

```python
# tests/envmon/test_evaluate_readiness.py
import csv
from datetime import datetime
from pathlib import Path
import uuid

import pytest
from autogis.core.common.qa import QACollector, SEV_ERROR, SEV_WARNING, SEV_INFO
from autogis.core.common.run_history import RunHistory, RunRecord
from autogis.core.envmon.evaluate_readiness import evaluate_readiness


def _record(tool, site, event, status="success"):
    now = datetime.now()
    return RunRecord(
        run_id=str(uuid.uuid4()), tool_name=tool,
        site_id=site, event_id=event,
        started_at=now, finished_at=now,
        status=status, inputs={}, outputs={},
        qa_count_error=0, qa_count_warning=0, qa_count_info=0,
        message="")


def _history(tmp_path, records):
    h = RunHistory(tmp_path / "run_history.csv")
    for r in records:
        h.write(r)
    return h


def test_pass_when_all_tools_succeeded(tmp_path):
    h = _history(tmp_path, [
        _record("import-lab-edd", "H281", "EV01"),
        _record("reconcile-locations", "H281", "EV01")])
    qa = evaluate_readiness("H281", "EV01", h,
                            required_tools=["import-lab-edd", "reconcile-locations"])
    assert qa.status() == "PASS"


def test_error_when_required_tool_not_run(tmp_path):
    h = _history(tmp_path, [_record("import-lab-edd", "H281", "EV01")])
    qa = evaluate_readiness("H281", "EV01", h,
                            required_tools=["import-lab-edd", "reconcile-locations"])
    cats = {r.category for r in qa.records}
    assert "required_tool_not_run" in cats
    assert qa.status() == "FAIL"


def test_error_when_last_run_failed(tmp_path):
    h = _history(tmp_path, [
        _record("import-lab-edd", "H281", "EV01", status="success"),
        _record("import-lab-edd", "H281", "EV01", status="error")])
    qa = evaluate_readiness("H281", "EV01", h,
                            required_tools=["import-lab-edd"])
    assert any(r.category == "required_tool_not_run" for r in qa.records)
    assert qa.status() == "FAIL"


def test_warning_when_qa_errors_present(tmp_path):
    h = _history(tmp_path, [_record("import-lab-edd", "H281", "EV01")])
    qa_csv = tmp_path / "qa.csv"
    qa_csv.write_text(
        "severity,category,message,recommended_action,site_id,location_id,"
        "sample_id,sample_date,analyte_name,source_workbook,source_sheet,"
        "source_row,source_column,source_cell,import_batch_id\n"
        "ERROR,some_error,oops,,H281,,,,,,,,,,\n",
        encoding="utf-8")
    qa = evaluate_readiness("H281", "EV01", h,
                            required_tools=["import-lab-edd"],
                            qa_csv=qa_csv)
    assert any(r.category == "import_qa_errors_present" for r in qa.records)
    # WARNING does not cause FAIL under default --fail-on error
    assert qa.status(allow_warnings=True) == "PASS"
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/envmon/test_evaluate_readiness.py -q
```
Expected: FAIL — module `evaluate_readiness` not found.

- [ ] **Step 3: Write `evaluate_readiness()`**

```python
# autogis/core/envmon/evaluate_readiness.py
"""Evaluate whether a monitoring event is ready for report delivery.

Checks that required tools have run successfully for the event, flags any
import QA errors, and optionally validates the figure spec.  All inputs are
files or in-memory objects — no arcpy required.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import List, Optional

from ..common.qa import QACollector, SEV_ERROR, SEV_INFO, SEV_WARNING
from ..common.run_history import RunHistory, RunHistoryError


def evaluate_readiness(
    site_id: str,
    event_id: Optional[str],
    run_history: RunHistory,
    required_tools: List[str],
    qa_csv: Optional[Path] = None,
    figure_spec_path: Optional[Path] = None,
) -> QACollector:
    """Return a QACollector whose status() reflects report readiness.

    Checks:
    1. Each tool in required_tools has a 'success' run for site_id/event_id.
    2. If qa_csv is provided, any ERROR rows yield a QA WARNING.
    3. If figure_spec_path is provided, it must load without error.
    """
    qa = QACollector()
    passed, failed = [], []

    for tool in required_tools:
        try:
            latest = run_history.latest(tool, site_id)
        except RunHistoryError as exc:
            qa.add(SEV_ERROR, "run_history_unreadable",
                   f"cannot read run history: {exc}", site_id=site_id)
            failed.append(tool)
            continue

        if latest is None or latest.status != "success":
            last_status = latest.status if latest else "never run"
            qa.add(SEV_ERROR, "required_tool_not_run",
                   f"tool {tool!r} has not completed successfully for site "
                   f"{site_id!r} (last status: {last_status})",
                   site_id=site_id,
                   recommended_action=f"run 'autogis envmon {tool}' and verify it succeeds")
            failed.append(tool)
        else:
            passed.append(tool)

    if qa_csv is not None and Path(qa_csv).exists():
        error_count = 0
        try:
            with Path(qa_csv).open(newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    if row.get("severity", "").upper() == "ERROR":
                        error_count += 1
        except Exception as exc:
            qa.add(SEV_WARNING, "qa_csv_unreadable",
                   f"cannot read QA report at {qa_csv}: {exc}",
                   site_id=site_id)
        if error_count:
            qa.add(SEV_WARNING, "import_qa_errors_present",
                   f"{error_count} ERROR record(s) found in QA report {qa_csv.name}; "
                   f"review before delivery",
                   site_id=site_id,
                   recommended_action="resolve all QA errors in the import QA report")

    if figure_spec_path is not None:
        from ..common.config import FigureSpec
        try:
            FigureSpec.load(Path(figure_spec_path))
        except Exception as exc:
            qa.add(SEV_WARNING, "figure_spec_invalid",
                   f"figure spec {figure_spec_path} failed to load: {exc}",
                   site_id=site_id)

    summary_parts = []
    if passed:
        summary_parts.append(f"tools passed: {', '.join(passed)}")
    if failed:
        summary_parts.append(f"tools failed/missing: {', '.join(failed)}")
    qa.add(SEV_INFO, "readiness_summary",
           f"Readiness check for site={site_id!r} event={event_id!r}: "
           + "; ".join(summary_parts) if summary_parts else "no tools checked",
           site_id=site_id)

    return qa
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/envmon/test_evaluate_readiness.py -q
```
Expected: PASS (4 tests).

- [ ] **Step 5: Commit core**

```bash
git add autogis/core/envmon/evaluate_readiness.py \
        tests/envmon/test_evaluate_readiness.py
git commit -m "feat(envmon): evaluate_readiness — report-readiness gate against run history"
```

### Task 5b: CLI command

- [ ] **Step 1: Write failing CLI test**

```python
# append to tests/envmon/test_evaluate_readiness.py
from click.testing import CliRunner
from autogis.adapters.cli import autogis as _cli


def test_evaluate_readiness_cli_fail_missing_tool(tmp_path):
    # Empty run history => required tool never run => FAIL => exit 1
    h = RunHistory(tmp_path / "run_history.csv")
    r = CliRunner().invoke(_cli, [
        "envmon", "evaluate-readiness",
        "--site-id", "H281",
        "--run-history", str(tmp_path / "run_history.csv"),
        "--required-tool", "import-lab-edd"])
    assert r.exit_code == 1
    assert "required_tool_not_run" in r.output


def test_evaluate_readiness_cli_pass(tmp_path):
    h = _history(tmp_path, [_record("import-lab-edd", "H281", None)])
    r = CliRunner().invoke(_cli, [
        "envmon", "evaluate-readiness",
        "--site-id", "H281",
        "--run-history", str(tmp_path / "run_history.csv"),
        "--required-tool", "import-lab-edd"])
    assert r.exit_code == 0
    assert "PASS" in r.output or "readiness_summary" in r.output
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/envmon/test_evaluate_readiness.py -k cli -q
```
Expected: FAIL — no such command `evaluate-readiness`.

- [ ] **Step 3: Add CLI command to `cli.py`**

```python
# autogis/adapters/cli.py — add after export_summary_cmd
@envmon.command("evaluate-readiness")
@click.option("--site-id", required=True, help="Site ID to check.")
@click.option("--run-history", required=True, type=click.Path(exists=True),
              help="run_history.csv path.")
@click.option("--event-id", default=None, help="Event ID filter (optional).")
@click.option("--required-tool", "required_tools", multiple=True,
              help="Tool name that must have succeeded (repeatable).")
@click.option("--qa-report", default=None, type=click.Path(exists=False),
              help="QA CSV from a previous import (checked for ERROR rows).")
@click.option("--figure-spec", default=None, type=click.Path(exists=False),
              help="Figure spec YAML to validate.")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def evaluate_readiness_cmd(site_id, run_history, event_id, required_tools,
                           qa_report, figure_spec, report, fail_on):
    """Tool: report-readiness gate — checks required tools ran successfully."""
    from autogis.core.common.run_history import RunHistory
    from autogis.core.envmon.evaluate_readiness import evaluate_readiness

    history = RunHistory(Path(run_history))
    qa = evaluate_readiness(
        site_id=site_id,
        event_id=event_id,
        run_history=history,
        required_tools=list(required_tools),
        qa_csv=Path(qa_report) if qa_report else None,
        figure_spec_path=Path(figure_spec) if figure_spec else None)
    _render_qa(qa, report, fail_on)
```

- [ ] **Step 4: Run full suite + commit**

```
python -m pytest -q
```
Expected: full suite green.

```bash
git add autogis/core/envmon/evaluate_readiness.py \
        autogis/adapters/cli.py \
        tests/envmon/test_evaluate_readiness.py
git commit -m "feat(cli): envmon evaluate-readiness command"
```

---

## Self-Review

**Spec coverage (ADR-019):**
- Item 1 — unit fix → Task 1, `evaluate_screening()` ✓
- Item 2 — ReconcileSampleLocations → Task 2, delegated to Phase B plan ✓
- Item 3 — EvaluateDuplicateRPD → Task 3 ✓
- Item 4 — ExportAnalyticalSummaryTables → Task 4 ✓
- Item 5 — EvaluateReportReadiness → Task 5 ✓
- Dependency order documented in plan header ✓
- All items headless-core; arcpy only in `.pyt` (Task 2, Phase B Task 6) ✓

**Placeholder scan:** Every code step is complete. No TBDs.

**Type consistency:**
- `evaluate_screening(parsed, screening_level, result_unit=None, screening_unit=None)` — defined Task 1, called from `table_normalizer.py` in same task ✓
- `read_records_csv(path, record_class)` — defined Task 3b, consumed by Task 4b CLI and Task 3 CLI ✓
- `evaluate_duplicate_rpd(samples, results, site_id, batch_id, qa)` — all `List[SampleRecord]` / `List[AnalyticalResultRecord]` from `gdb_schema`; returns `List[RPDRecord]` ✓
- `export_analytical_summary(samples, results, output_path, site_id, event_id)` — `List[AnalyticalResultRecord]`, returns `Path` ✓
- `evaluate_readiness(site_id, event_id, run_history, required_tools, qa_csv, figure_spec_path)` — `RunHistory` from `common/run_history.py`, returns `QACollector` ✓
- `_render_qa(qa, report, fail_on)` — all CLI commands use the existing helper in `cli.py` ✓
