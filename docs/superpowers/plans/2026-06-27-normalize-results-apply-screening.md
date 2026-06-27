# NormalizeResultsAndApplyScreening (Tool 3.5) — Implementation Plan

**Goal:** Add a headless `envmon apply-screening` CLI command + core module that reads
a CSV of `AnalyticalResultRecord`s, re-evaluates `ExceedsScreeningLevel` using the
existing `units.py` unit-conversion gate, and writes updated records. This fills in
`ExceedsScreeningLevel` / `DisplayColorClass` for records that arrived without
screening values (common after bare CSV imports without a screening-levels file).

**Architecture:** New pure-core module `autogis/core/envmon/apply_screening.py` with
`apply_screening_levels(results, screening_levels, *, qa) -> list[AnalyticalResultRecord]`.
A single `click` command reads results CSV + screening YAML, calls the function, writes
updated records to CSV, renders QA + exit via `_render_qa`. No arcpy, no openpyxl.

**Tech stack:** Python 3.14, `click`, `pyyaml`, stdlib `csv`/`dataclasses`,
`pytest`. Reuses: `AnalyticalResultRecord` (`gdb_schema.py`),
`read_records_csv` (`evaluate_rpd_qa.py`), `same_dimension`/`convert` (`common/units.py`),
`QACollector` (`common/qa.py`), `_render_qa` (`cli.py`).

## Global constraints

- `core/` and `adapters/` import without arcpy. Headless — no `_guard`.
- Command name exactly `apply-screening`. Register as `Runtime.CLOUD`.
- The screening YAML format is the same as used by `validate_units_cmd`
  (`--screening` option): `analyte_canonical_name -> {matrix -> {unit, level}}`.
- Unit conversion uses `same_dimension` + `convert` from `common/units.py` (ADR-022).
  If units are not convertible: emit WARNING `unit_conversion_failed`, leave
  `ExceedsScreeningLevel` as-is (or None).
- Records where `ResultNumeric is None` (non-detects) set `ExceedsScreeningLevel=0`
  unless the non-detect reporting limit exceeds the screening level (in which case
  set it to 0 — non-detects do not trigger exceedances).
- `DisplayColorClass` mapping: `ExceedsScreeningLevel=1` → `"EXCEED"`,
  `ExceedsScreeningLevel=0` → `"OK"`, `None` → `"UNKNOWN"`.

---

### Task 1: Core module `apply_screening.py` + unit tests

**Files:**
- Create: `autogis/core/envmon/apply_screening.py`
- Create: `tests/test_apply_screening.py`

**Interfaces:**
- `screening_levels`: `dict[str, dict[str, dict]]` → canonical_name →
  matrix → `{unit: str, level: float}`.
- `apply_screening_levels(results, screening_levels, *, qa) -> list[AnalyticalResultRecord]`
  Returns new `AnalyticalResultRecord` instances (copies) with updated
  `ScreeningLevel`, `ScreeningLevelSource`, `ExceedsScreeningLevel`,
  `DisplayColorClass` fields.

**Complete code skeleton:**

```python
"""Re-evaluate ExceedsScreeningLevel on existing records (Tool 3.5)."""
from __future__ import annotations
import dataclasses
from typing import List
from .gdb_schema import AnalyticalResultRecord
from ..common.units import same_dimension, convert
from ..common.qa import QACollector, SEV_INFO, SEV_WARNING


def apply_screening_levels(
    results: List[AnalyticalResultRecord],
    screening_levels: dict,
    *,
    qa: QACollector,
) -> List[AnalyticalResultRecord]:
    updated = []
    changed = 0
    for r in results:
        sl_entry = (screening_levels
                    .get(r.AnalyteCanonicalName, {})
                    .get(r.Matrix, {}))
        if not sl_entry:
            updated.append(r)
            continue
        sl_val = sl_entry.get("level")
        sl_unit = sl_entry.get("unit", r.Units)
        sl_source = sl_entry.get("source", "")
        if sl_val is None:
            updated.append(r)
            continue
        # Unit conversion.
        result_val = r.ResultNumeric
        if result_val is None:
            # Non-detect never exceeds.
            new_exceed = 0
        elif r.Units != sl_unit:
            try:
                if not same_dimension(r.Units, sl_unit):
                    raise ValueError(f"incompatible dimensions: {r.Units} vs {sl_unit}")
                result_val = convert(result_val, r.Units, sl_unit)
                new_exceed = 1 if result_val > sl_val else 0
            except Exception as exc:
                qa.add(SEV_WARNING, "unit_conversion_failed",
                       f"{r.LocationID}/{r.AnalyteCanonicalName}: {exc}",
                       location_id=r.LocationID, analyte_name=r.AnalyteCanonicalName)
                updated.append(r)
                continue
        else:
            new_exceed = 1 if result_val > sl_val else 0
        color = {1: "EXCEED", 0: "OK"}.get(new_exceed, "UNKNOWN")
        new_r = dataclasses.replace(
            r, ScreeningLevel=sl_val, ScreeningLevelSource=sl_source,
            ExceedsScreeningLevel=new_exceed, DisplayColorClass=color)
        if new_r != r:
            changed += 1
        updated.append(new_r)
    qa.add(SEV_INFO, "apply_screening_complete",
           f"apply_screening_levels: {changed} record(s) updated out of {len(results)}")
    return updated
```

**Test file `tests/test_apply_screening.py`:**

```python
"""Unit tests for apply_screening (Tool 3.5)."""
from datetime import date
from autogis.core.common.qa import QACollector
from autogis.core.envmon.apply_screening import apply_screening_levels
from autogis.core.envmon.gdb_schema import AnalyticalResultRecord

def _r(analyte, num, units="ug/L", matrix="GW", exceed=None):
    return AnalyticalResultRecord(
        ImportBatchID="B", SiteID="S", Matrix=matrix,
        LocationID="MW-1", SampleID="S1", ParentSampleID="", SampleDate=date(2026, 4, 1),
        DepthTop_ft=None, DepthBottom_ft=None, DepthIntervalText="",
        AnalyticalGroup="VOC", MethodGroup="EPA8260", AnalyteName=analyte,
        AnalyteCanonicalName=analyte, AnalyteAbbreviation=analyte[:3],
        ResultRawText=str(num), ResultNumeric=num, ReportingLimit=None,
        DetectionLimit=None, Units=units, Qualifier="", IsNonDetect=0,
        IsDetected=1, IsEstimated=0, IsDiluted=0, IsNotAnalyzed=0,
        IsNotSampled=0, IsNotMeasured=0, ScreeningLevel=None,
        ScreeningLevelSource="", ExceedsScreeningLevel=exceed, DisplayText=str(num),
        DisplayColorClass="", SourceWorkbook="t.xlsx", SourceSheet="S1",
        SourceRow=1, SourceColumn="A", SourceCell="A1")

SCREENING = {"Benzene": {"GW": {"unit": "ug/L", "level": 5.0, "source": "RBSL"}}}

def test_exceedance_detected():
    qa = QACollector()
    results = apply_screening_levels([_r("Benzene", 10.0)], SCREENING, qa=qa)
    assert results[0].ExceedsScreeningLevel == 1
    assert results[0].DisplayColorClass == "EXCEED"

def test_no_exceedance():
    qa = QACollector()
    results = apply_screening_levels([_r("Benzene", 3.0)], SCREENING, qa=qa)
    assert results[0].ExceedsScreeningLevel == 0
    assert results[0].DisplayColorClass == "OK"

def test_nondetect_never_exceeds():
    r = _r("Benzene", None)
    r = r.__class__(**{**r.__dict__, "IsNonDetect": 1, "IsDetected": 0})
    qa = QACollector()
    results = apply_screening_levels([r], SCREENING, qa=qa)
    assert results[0].ExceedsScreeningLevel == 0

def test_no_screening_level_passthrough():
    qa = QACollector()
    results = apply_screening_levels([_r("Toluene", 99.0)], SCREENING, qa=qa)
    assert results[0].ExceedsScreeningLevel is None  # unchanged
```

**Steps:**
- [ ] Write test file, verify ImportError.
- [ ] Implement `apply_screening.py`.
- [ ] Run unit tests, verify pass.

---

### Task 2: Wire CLI + register

**Command:**

```python
@envmon.command("apply-screening")
@click.option("--results-csv", required=True, type=click.Path(exists=True))
@click.option("--screening", required=True, type=click.Path(exists=True))
@click.option("--output", required=True, type=click.Path())
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def apply_screening_cmd(results_csv, screening, output, report, fail_on):
    """Tool 3.5: re-evaluate ExceedsScreeningLevel on result records."""
    ...
```

`capabilities.py`: `"apply-screening": Runtime.CLOUD`

**Steps:**
- [ ] Write failing CLI test, verify fail.
- [ ] Add command, update capabilities.
- [ ] Run full suite, verify no regressions.
- [ ] Commit: `feat(envmon): apply-screening — re-evaluate screening exceedance on records (Tool 3.5)`
