# BuildMaxResultMapDataset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `BuildMaxResultMapDataset` — cross-event aggregation of long-format results to max-detected per location-analyte pair.
See spec: `docs/superpowers/specs/2026-06-28-build-max-result-dataset-design.md`.

**Architecture:**
- New: `autogis/core/envmon/max_result_dataset.py`
- Modify: `autogis/adapters/cli.py` — add `build-max-result-dataset` command (headless)
- New: `tests/envmon/test_max_result_dataset.py`

## Global Constraints

- Arcpy-free. stdlib only: `csv`, `dataclasses`.
- ND rows skipped by default; `include_nd=True` allows all-ND records.
- Run tests with `python -m pytest -q`.

---

### Task 1: Core `max_result_dataset.py`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_max_result_dataset.py`:

```python
import pytest
from autogis.core.envmon.max_result_dataset import (
    build_max_result_dataset, MaxResultRecord,
)

_ROWS = [
    {"LocationID": "MW-01", "AnalyteName": "Benzene",
     "ResultValue": "5.2", "ResultQualifier": "", "ReportedUnits": "ug/L",
     "SampleDate": "2026-01-15", "SampleID": "S1"},
    {"LocationID": "MW-01", "AnalyteName": "Benzene",
     "ResultValue": "12.0", "ResultQualifier": "", "ReportedUnits": "ug/L",
     "SampleDate": "2026-06-15", "SampleID": "S2"},
    {"LocationID": "MW-01", "AnalyteName": "Benzene",
     "ResultValue": "ND", "ResultQualifier": "ND", "ReportedUnits": "ug/L",
     "SampleDate": "2025-06-15", "SampleID": "S0"},
    {"LocationID": "MW-02", "AnalyteName": "Benzene",
     "ResultValue": "ND", "ResultQualifier": "ND", "ReportedUnits": "ug/L",
     "SampleDate": "2026-01-15", "SampleID": "S3"},
]
_SL = {"Benzene": 5.0}


def test_max_detected_selected():
    records = build_max_result_dataset(_ROWS)
    mw01 = next(r for r in records if r.location_id == "MW-01")
    assert mw01.max_result_value == 12.0
    assert mw01.max_sample_id == "S2"


def test_detection_count():
    records = build_max_result_dataset(_ROWS)
    mw01 = next(r for r in records if r.location_id == "MW-01")
    assert mw01.detection_count == 2
    assert mw01.total_sample_count == 3


def test_all_nd_excluded_by_default():
    records = build_max_result_dataset(_ROWS)
    ids = [r.location_id for r in records]
    assert "MW-02" not in ids


def test_all_nd_included_with_flag():
    records = build_max_result_dataset(_ROWS, include_nd=True)
    ids = [r.location_id for r in records]
    assert "MW-02" in ids


def test_exceedance_ratio_computed():
    records = build_max_result_dataset(_ROWS, screening_levels=_SL)
    mw01 = next(r for r in records if r.location_id == "MW-01")
    assert mw01.exceedance_ratio == pytest.approx(12.0 / 5.0)
    assert mw01.has_exceedance is True


def test_date_filter():
    records = build_max_result_dataset(_ROWS, date_from="2026-01-01")
    mw01 = next(r for r in records if r.location_id == "MW-01")
    assert mw01.total_sample_count == 2  # S0 excluded


def test_analyte_filter():
    records = build_max_result_dataset(_ROWS, analytes=["Toluene"])
    assert len(records) == 0  # no Toluene rows


def test_first_last_detection_dates():
    records = build_max_result_dataset(_ROWS)
    mw01 = next(r for r in records if r.location_id == "MW-01")
    assert mw01.first_detection_date == "2026-01-15"
    assert mw01.last_detection_date == "2026-06-15"
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_max_result_dataset.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/max_result_dataset.py`**

```python
"""max_result_dataset.py — cross-event max-detected aggregation."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, QARecord, SEV_INFO

ND_QUALIFIERS = frozenset({"ND", "U", "BDL"})


@dataclass
class MaxResultRecord:
    location_id: str
    analyte_name: str
    max_result_value: Optional[float]
    max_result_qualifier: str
    reported_units: str
    max_sample_date: str
    max_sample_id: str
    detection_count: int
    total_sample_count: int
    screening_level: Optional[float]
    exceedance_ratio: Optional[float]
    has_exceedance: bool
    first_detection_date: str
    last_detection_date: str


def _parse_num(v: str) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_max_result_dataset(
    result_rows: list,
    *,
    screening_levels: Optional[dict] = None,
    analytes: Optional[list] = None,
    wells: Optional[list] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    include_nd: bool = False,
    nd_qualifiers: frozenset = ND_QUALIFIERS,
    qa: Optional[QACollector] = None,
) -> list:
    if qa is None:
        qa = QACollector()
    sl = screening_levels or {}

    # Filters
    rows = result_rows
    if analytes:
        rows = [r for r in rows if r.get("AnalyteName") in analytes]
    if wells:
        rows = [r for r in rows if r.get("LocationID") in wells]
    if date_from:
        rows = [r for r in rows if r.get("SampleDate", "") >= date_from]
    if date_to:
        rows = [r for r in rows if r.get("SampleDate", "") <= date_to]

    # Group
    groups: dict[tuple, list] = {}
    for r in rows:
        key = (r.get("LocationID", ""), r.get("AnalyteName", ""))
        groups.setdefault(key, []).append(r)

    records = []
    for (loc, analyte), grp in groups.items():
        total = len(grp)
        detected = [r for r in grp
                    if r.get("ResultQualifier", "").upper().strip() not in nd_qualifiers
                    and _parse_num(r.get("ResultValue", "")) is not None]

        if not detected and not include_nd:
            continue

        detection_dates = sorted(r.get("SampleDate", "") for r in detected)
        first_det = detection_dates[0] if detection_dates else ""
        last_det  = detection_dates[-1] if detection_dates else ""

        if detected:
            best = max(detected, key=lambda r: _parse_num(r.get("ResultValue", "")) or 0)
            val = _parse_num(best.get("ResultValue", ""))
            qual = best.get("ResultQualifier", "")
            date = best.get("SampleDate", "")
            sid  = best.get("SampleID", "")
        else:
            best = max(grp, key=lambda r: r.get("SampleDate", ""))
            val = None
            qual = best.get("ResultQualifier", "ND")
            date = best.get("SampleDate", "")
            sid  = best.get("SampleID", "")

        screening = sl.get(analyte)
        ratio = (val / screening) if (val is not None and screening) else None
        has_exceedance = ratio is not None and ratio >= 1.0

        records.append(MaxResultRecord(
            location_id=loc, analyte_name=analyte,
            max_result_value=val, max_result_qualifier=qual,
            reported_units=best.get("ReportedUnits", ""),
            max_sample_date=date, max_sample_id=sid,
            detection_count=len(detected), total_sample_count=total,
            screening_level=screening,
            exceedance_ratio=round(ratio, 4) if ratio is not None else None,
            has_exceedance=has_exceedance,
            first_detection_date=first_det, last_detection_date=last_det,
        ))

    qa.add(QARecord(SEV_INFO, "max_result_built",
                    f"{len(records)} location-analyte max records built"))
    return records


def write_max_result_csv(records: list, path: Path) -> None:
    import dataclasses
    if not records:
        Path(path).write_text("")
        return
    fields = [f.name for f in dataclasses.fields(records[0])]
    with Path(path).open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in records:
            w.writerow(dataclasses.asdict(r))
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_max_result_dataset.py -v
```

Expected: all 8 PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add autogis/core/envmon/max_result_dataset.py \
        tests/envmon/test_max_result_dataset.py
git commit -m "feat(envmon): max_result_dataset — cross-event max-detected aggregation"
```

---

### Task 2: CLI command

- [ ] **Step 1: Add to `cli.py`**

```python
@envmon.command("build-max-result-dataset")
@click.option("--results", "results_path", required=True, type=click.Path(exists=True))
@click.option("--screening-levels", "sl_path", default=None, type=click.Path(exists=True))
@click.option("--analytes", default=None)
@click.option("--wells", default=None)
@click.option("--date-from", default=None)
@click.option("--date-to", default=None)
@click.option("--include-nd", is_flag=True, default=False)
@click.option("--out", required=True, type=click.Path())
@click.option("--report", default=None, type=click.Path())
def build_max_result_dataset_cmd(results_path, sl_path, analytes, wells,
                                  date_from, date_to, include_nd, out, report):
    """Build max-detected dataset across all events (headless)."""
    import csv as _csv, yaml as _yaml
    from autogis.core.envmon.max_result_dataset import (
        build_max_result_dataset, write_max_result_csv)
    from autogis.core.common.qa import QACollector

    with open(results_path, newline="", encoding="utf-8") as fh:
        rows = list(_csv.DictReader(fh))
    sl = _yaml.safe_load(Path(sl_path).read_text()) if sl_path else None
    qa = QACollector()
    records = build_max_result_dataset(
        rows, screening_levels=sl,
        analytes=[a.strip() for a in analytes.split(",")] if analytes else None,
        wells=[w.strip() for w in wells.split(",")] if wells else None,
        date_from=date_from, date_to=date_to, include_nd=include_nd, qa=qa,
    )
    write_max_result_csv(records, Path(out))
    exceed = sum(1 for r in records if r.has_exceedance)
    click.echo(f"Records: {len(records)}  Exceedances: {exceed}  Output: {out}")
    _render_qa(qa, report, "warning")
```

- [ ] **Step 2: Help test + commit**

```python
def test_build_max_result_dataset_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "build-max-result-dataset" in result.output
```

```bash
git add autogis/adapters/cli.py tests/envmon/test_max_result_dataset.py
git commit -m "feat(cli): add build-max-result-dataset command"
```
