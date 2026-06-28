# ImportRTKSurveyPoints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `ImportRTKSurveyPoints` — parse CSV/TXT RTK survey exports into
`SurveyPoints_Raw` and `SurveyPoints_QA` GDB tables, with pure-Python parsing and LOCAL
GDB write.

**Architecture:**
- New: `autogis/core/envmon/import_rtk_survey.py`
- Modify: `autogis/adapters/cli.py` — add `import-rtk-survey` command (LOCAL)
- New: `tests/envmon/test_import_rtk_survey.py`

## Global Constraints

- Branch: `feat/gdb-schema-upgrade`
- Parsing (CSV → dataclasses) is arcpy-free and fully testable.
- GDB write is LOCAL (`# pragma: no cover`).
- Coordinate columns: Northing, Easting, Elevation_ft (or Y, X, Z — configurable).
- Run tests with `python -m pytest -q`.

---

### Task 1: `import_rtk_survey.py` + tests

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_import_rtk_survey.py`:

```python
import csv
from pathlib import Path
from autogis.core.envmon.import_rtk_survey import (
    RTKPoint, RTKColumnMap, parse_rtk_csv, assign_qa_flags,
)

_CSV_CONTENT = """\
PointID,Northing,Easting,Elevation_ft,FeatureCode,Description,HRMS_ft,VRMS_ft,FixType,CollectedAt,Operator
MW-01,4527893.12,293847.55,512.34,WELL,Monitoring Well,0.01,0.02,RTK_FIXED,2026-06-15,Alice
MW-02,4527750.00,293900.00,509.12,WELL,Monitoring Well,0.05,0.08,RTK_FLOAT,2026-06-15,Alice
INV001,4527800.00,293870.00,510.00,INV,Invalid high precision,0.50,0.80,AUTONOMOUS,2026-06-15,Alice
"""


def _write_csv(tmp_path, content=_CSV_CONTENT):
    p = tmp_path / "rtk.csv"
    p.write_text(content, encoding="utf-8")
    return p


def test_parse_rtk_csv_count(tmp_path):
    points = parse_rtk_csv(_write_csv(tmp_path))
    assert len(points) == 3


def test_parse_rtk_csv_northing(tmp_path):
    points = parse_rtk_csv(_write_csv(tmp_path))
    assert abs(points[0].northing - 4527893.12) < 0.001


def test_parse_rtk_csv_point_id(tmp_path):
    points = parse_rtk_csv(_write_csv(tmp_path))
    assert points[0].point_id == "MW-01"


def test_assign_qa_flags_fixed_no_flags(tmp_path):
    points = parse_rtk_csv(_write_csv(tmp_path))
    mw01 = next(p for p in points if p.point_id == "MW-01")
    flags = assign_qa_flags(mw01, hrms_threshold_ft=0.03, vrms_threshold_ft=0.05)
    assert flags == []


def test_assign_qa_flags_poor_hrms(tmp_path):
    points = parse_rtk_csv(_write_csv(tmp_path))
    mw02 = next(p for p in points if p.point_id == "MW-02")
    flags = assign_qa_flags(mw02, hrms_threshold_ft=0.03, vrms_threshold_ft=0.05)
    assert "hrms_exceeds_threshold" in flags


def test_assign_qa_flags_autonomous_fix(tmp_path):
    points = parse_rtk_csv(_write_csv(tmp_path))
    inv = next(p for p in points if p.point_id == "INV001")
    flags = assign_qa_flags(inv, hrms_threshold_ft=0.10, vrms_threshold_ft=0.10)
    assert "fix_type_not_rtk" in flags


def test_custom_column_map(tmp_path):
    content = "ID,Y,X,Z,Code\nMW-01,4527893.12,293847.55,512.34,WELL\n"
    p = tmp_path / "custom.csv"
    p.write_text(content, encoding="utf-8")
    cm = RTKColumnMap(point_id="ID", northing="Y", easting="X",
                      elevation_ft="Z", feature_code="Code")
    points = parse_rtk_csv(p, column_map=cm)
    assert len(points) == 1
    assert points[0].northing == 4527893.12
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_import_rtk_survey.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/import_rtk_survey.py`**

```python
"""import_rtk_survey.py — parse RTK survey CSV → SurveyPoints_Raw/QA GDB tables."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class RTKColumnMap:
    point_id: str = "PointID"
    northing: str = "Northing"
    easting: str = "Easting"
    elevation_ft: str = "Elevation_ft"
    feature_code: str = "FeatureCode"
    description: str = "Description"
    hrms_ft: str = "HRMS_ft"
    vrms_ft: str = "VRMS_ft"
    fix_type: str = "FixType"
    collected_at: str = "CollectedAt"
    operator: str = "Operator"

    RTK_FIX_TYPES = frozenset({"RTK_FIXED", "RTK_FLOAT", "NETWORK_RTK"})


@dataclass
class RTKPoint:
    point_id: str
    northing: float
    easting: float
    elevation_ft: float
    feature_code: str = ""
    description: str = ""
    hrms_ft: Optional[float] = None
    vrms_ft: Optional[float] = None
    fix_type: str = ""
    collected_at: str = ""
    operator: str = ""


def _f(row, key, default=None):
    v = row.get(key, "").strip()
    if not v:
        return default
    try:
        return float(v)
    except ValueError:
        return default


def parse_rtk_csv(
    path: Path,
    column_map: Optional[RTKColumnMap] = None,
) -> list[RTKPoint]:
    cm = column_map or RTKColumnMap()
    out: list[RTKPoint] = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            n = _f(row, cm.northing)
            e = _f(row, cm.easting)
            z = _f(row, cm.elevation_ft)
            if n is None or e is None or z is None:
                continue
            out.append(RTKPoint(
                point_id=row.get(cm.point_id, "").strip(),
                northing=n, easting=e, elevation_ft=z,
                feature_code=row.get(cm.feature_code, "").strip(),
                description=row.get(cm.description, "").strip(),
                hrms_ft=_f(row, cm.hrms_ft),
                vrms_ft=_f(row, cm.vrms_ft),
                fix_type=row.get(cm.fix_type, "").strip(),
                collected_at=row.get(cm.collected_at, "").strip(),
                operator=row.get(cm.operator, "").strip(),
            ))
    return out


_RTK_FIX_TYPES = frozenset({"RTK_FIXED", "RTK_FLOAT", "NETWORK_RTK"})


def assign_qa_flags(
    point: RTKPoint,
    hrms_threshold_ft: float = 0.03,
    vrms_threshold_ft: float = 0.05,
) -> list[str]:
    flags: list[str] = []
    if point.hrms_ft is not None and point.hrms_ft > hrms_threshold_ft:
        flags.append("hrms_exceeds_threshold")
    if point.vrms_ft is not None and point.vrms_ft > vrms_threshold_ft:
        flags.append("vrms_exceeds_threshold")
    if point.fix_type and point.fix_type.upper() not in _RTK_FIX_TYPES:
        flags.append("fix_type_not_rtk")
    return flags


def import_rtk_survey(    # pragma: no cover
    gdb_path: str,
    site_id: str,
    batch_id: str,
    points: list[RTKPoint],
    hrms_threshold_ft: float = 0.03,
    vrms_threshold_ft: float = 0.05,
) -> None:
    """Write RTKPoint list to SurveyPoints_Raw and SurveyPoints_QA (ArcGIS Pro)."""
    import arcpy
    from pathlib import Path as _P
    from ...runtime.sessions import arcpy_env as _arcpy
    _ax = _arcpy()
    gdb = str(gdb_path)

    raw_table = str(_P(gdb) / "SurveyPoints_Raw")
    qa_table = str(_P(gdb) / "SurveyPoints_QA")
    import json

    if _ax.Exists(raw_table):
        with _ax.da.InsertCursor(raw_table,
                                 ["PointID", "Northing", "Easting", "Elevation_ft",
                                  "FeatureCode", "Description", "HRMS_ft", "VRMS_ft",
                                  "FixType", "CollectedAt", "Operator"]) as cur:
            for pt in points:
                cur.insertRow([pt.point_id, pt.northing, pt.easting, pt.elevation_ft,
                               pt.feature_code, pt.description, pt.hrms_ft, pt.vrms_ft,
                               pt.fix_type, pt.collected_at, pt.operator])

    if _ax.Exists(qa_table):
        with _ax.da.InsertCursor(qa_table,
                                 ["PointID", "QAStatus", "QAFlags", "Approved"]) as cur:
            for pt in points:
                flags = assign_qa_flags(pt, hrms_threshold_ft, vrms_threshold_ft)
                status = "FAIL" if flags else "PASS"
                cur.insertRow([pt.point_id, status, json.dumps(flags), 0])
```

- [ ] **Step 4: Run tests + full suite + commit**

```bash
git add autogis/core/envmon/import_rtk_survey.py tests/envmon/test_import_rtk_survey.py
git commit -m "feat(envmon): import_rtk_survey — RTKPoint + parse_csv + assign_qa_flags"
```

---

### Task 2: CLI command `import-rtk-survey`

```python
@envmon.command("import-rtk-survey")
@click.argument("csv_path", metavar="CSV", type=click.Path(exists=True))
@click.option("--site", "site_id", required=True)
@click.option("--gdb", required=True, type=click.Path())
@click.option("--batch-id", default=None)
@click.option("--hrms-threshold", type=float, default=0.03, show_default=True)
@click.option("--vrms-threshold", type=float, default=0.05, show_default=True)
def import_rtk_survey_cmd(csv_path, site_id, gdb, batch_id, hrms_threshold, vrms_threshold):
    """Import RTK survey CSV into SurveyPoints_Raw/QA (ArcGIS Pro)."""
    import uuid
    _guard("import-rtk-survey")
    from autogis.core.envmon.import_rtk_survey import parse_rtk_csv, import_rtk_survey
    bid = batch_id or f"RTK-{uuid.uuid4().hex[:8].upper()}"
    points = parse_rtk_csv(Path(csv_path))
    import_rtk_survey(gdb, site_id, bid, points, hrms_threshold, vrms_threshold)
    passes = sum(1 for p in points if not assign_qa_flags(p, hrms_threshold, vrms_threshold))
    click.echo(f"Imported {len(points)} points: {passes} QA pass, {len(points)-passes} QA fail.")
```

Commit:
```bash
git add autogis/adapters/cli.py
git commit -m "feat(cli): add import-rtk-survey command (LOCAL)"
```
