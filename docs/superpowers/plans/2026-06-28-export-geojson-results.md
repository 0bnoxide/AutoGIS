# ExportGeoJSONResults — Implementation Plan

**Goal:** Add `envmon export-geojson` CLI command that exports `AnalyticalResultRecord`s with location coordinates (from a well coordinates CSV) to a GeoJSON FeatureCollection. Each feature is a monitoring location with properties: all analytes for the latest event, exceedance flags, and trend versus previous. Enables direct consumption by web mapping tools and ArcGIS Online without ArcGIS Pro.

**Architecture:** New module `autogis/core/envmon/export_geojson.py`. Input: results CSV + well-coordinates CSV (`location_id, x, y`). Output: GeoJSON FeatureCollection (one Feature per location, one property set per analyte from the latest sampling event). All logic in pure Python using stdlib `json`. CLOUD runtime — no arcpy required.

**Tech stack:** Python 3.14, click, stdlib json/csv/dataclasses. Reuses: `AnalyticalResultRecord` from `autogis/core/envmon/gdb_schema.py`, `QACollector` from `autogis/core/common/qa.py`.

## Global constraints
- `core/` and `adapters/` import without arcpy or arcgis present
- Use openpyxl for Excel (ADR-008) — this plan uses no Excel
- New CLI command added to TOOLS in `autogis/runtime/capabilities.py` as `Runtime.CLOUD`
- Run tests with: `python -m pytest -q`
- CLI command goes in `autogis/adapters/cli.py` under the `envmon` group

---

### Task 1: Write `tests/test_export_geojson.py`

**Files:**
- Create: `tests/test_export_geojson.py`

**Complete code:**

```python
"""Tests for export_geojson module (Tool 10.3)."""
from datetime import date

import pytest

from autogis.core.common.qa import QACollector
from autogis.core.envmon.export_geojson import build_geojson, load_well_coords
from autogis.core.envmon.gdb_schema import AnalyticalResultRecord


def _r(loc, analyte, num, dt, exceed=None):
    return AnalyticalResultRecord(
        ImportBatchID="B", SiteID="S", Matrix="GW",
        LocationID=loc, SampleID="S1", ParentSampleID="",
        SampleDate=dt, DepthTop_ft=None, DepthBottom_ft=None,
        DepthIntervalText="", AnalyticalGroup="VOC", MethodGroup="EPA8260",
        AnalyteName=analyte, AnalyteCanonicalName=analyte,
        AnalyteAbbreviation=analyte[:3], ResultRawText=str(num),
        ResultNumeric=num, ReportingLimit=None, DetectionLimit=None,
        Units="ug/L", Qualifier="", IsNonDetect=0, IsDetected=1,
        IsEstimated=0, IsDiluted=0, IsNotAnalyzed=0, IsNotSampled=0,
        IsNotMeasured=0, ScreeningLevel=None, ScreeningLevelSource="",
        ExceedsScreeningLevel=exceed, DisplayText=str(num), DisplayColorClass="",
        SourceWorkbook="t.xlsx", SourceSheet="S1",
        SourceRow=1, SourceColumn="A", SourceCell="A1",
    )


COORDS = {"MW-1": (100.0, 200.0), "MW-2": (110.0, 205.0)}


def test_basic_feature_count():
    results = [_r("MW-1", "Benzene", 5.0, date(2026, 4, 1))]
    qa = QACollector()
    fc = build_geojson(results, COORDS, qa=qa)
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 1


def test_missing_coords_skipped():
    results = [_r("MW-99", "Benzene", 5.0, date(2026, 4, 1))]
    qa = QACollector()
    fc = build_geojson(results, COORDS, qa=qa)
    assert len(fc["features"]) == 0
    assert any(r.category == "missing_coords" for r in qa.records)


def test_properties_contain_analyte():
    results = [_r("MW-1", "Benzene", 5.0, date(2026, 4, 1))]
    qa = QACollector()
    fc = build_geojson(results, COORDS, qa=qa)
    props = fc["features"][0]["properties"]
    assert "Benzene_value" in props
    assert props["Benzene_value"] == "5.0"


def test_geometry_coordinates():
    results = [_r("MW-1", "Benzene", 5.0, date(2026, 4, 1))]
    qa = QACollector()
    fc = build_geojson(results, COORDS, qa=qa)
    geom = fc["features"][0]["geometry"]
    assert geom["type"] == "Point"
    assert geom["coordinates"] == [100.0, 200.0]


def test_multi_location_multi_analyte():
    results = [
        _r("MW-1", "Benzene", 5.0, date(2026, 4, 1)),
        _r("MW-1", "Toluene", 2.5, date(2026, 4, 1)),
        _r("MW-2", "Benzene", 1.0, date(2026, 4, 1)),
    ]
    qa = QACollector()
    fc = build_geojson(results, COORDS, qa=qa)
    assert len(fc["features"]) == 2
    mw1_props = next(
        f["properties"] for f in fc["features"]
        if f["properties"]["location_id"] == "MW-1"
    )
    assert "Benzene_value" in mw1_props
    assert "Toluene_value" in mw1_props


def test_load_well_coords(tmp_path):
    csv_path = tmp_path / "coords.csv"
    csv_path.write_text("location_id,x,y\nMW-1,100.0,200.0\nMW-2,110.0,205.0\n",
                        encoding="utf-8")
    coords = load_well_coords(csv_path)
    assert coords["MW-1"] == (100.0, 200.0)
    assert coords["MW-2"] == (110.0, 205.0)


def test_is_not_analyzed_excluded():
    """Records with IsNotAnalyzed=1 must be excluded from output."""
    rec = _r("MW-1", "Benzene", 5.0, date(2026, 4, 1))
    rec = rec.__class__(
        **{**rec.__dict__, "IsNotAnalyzed": 1}
        if hasattr(rec, "__dict__") else
        {f.name: (1 if f.name == "IsNotAnalyzed" else getattr(rec, f.name))
         for f in rec.__class__.__dataclass_fields__.values()}
    )
    # Alternatively: use dataclasses.replace
    import dataclasses
    rec2 = dataclasses.replace(rec, IsNotAnalyzed=1)
    qa = QACollector()
    fc = build_geojson([rec2], COORDS, qa=qa)
    assert len(fc["features"]) == 0


def test_qa_info_emitted():
    results = [_r("MW-1", "Benzene", 5.0, date(2026, 4, 1))]
    qa = QACollector()
    build_geojson(results, COORDS, qa=qa)
    assert any(r.category == "export_geojson_complete" for r in qa.records)
```

**Steps:**
- [ ] Write test file
- [ ] Run `python -m pytest tests/test_export_geojson.py -q` — expect ImportError (module not yet created)

---

### Task 2: Create `autogis/core/envmon/export_geojson.py`

**Files:**
- Create: `autogis/core/envmon/export_geojson.py`

**Complete code:**

```python
"""Export analytical results to GeoJSON FeatureCollection (Tool 10.3).

No arcpy dependency. Pure stdlib: json, csv, collections.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from autogis.core.common.qa import QACollector, SEV_INFO, SEV_WARNING
from autogis.core.envmon.gdb_schema import AnalyticalResultRecord


def load_well_coords(path: Path) -> Dict[str, Tuple[float, float]]:
    """Load location_id -> (x, y) from a CSV with columns: location_id, x, y."""
    coords: Dict[str, Tuple[float, float]] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            coords[row["location_id"]] = (float(row["x"]), float(row["y"]))
    return coords


def build_geojson(
    results: List[AnalyticalResultRecord],
    coords: Dict[str, Tuple[float, float]],
    *,
    qa: QACollector,
) -> dict:
    """Build a GeoJSON FeatureCollection from analytical results.

    One Feature per location. Properties include latest value, exceedance flag,
    and sample date for each analyte found at that location.

    Args:
        results: List of AnalyticalResultRecord (arcpy-free dataclass).
        coords: Mapping of location_id -> (x, y) in the CRS of your choice.
        qa: QACollector for warnings (e.g. missing coords).

    Returns:
        GeoJSON FeatureCollection dict (serialise with json.dumps).
    """
    # Group by location
    by_loc: Dict[str, List[AnalyticalResultRecord]] = defaultdict(list)
    for r in results:
        if r.IsNotAnalyzed:
            continue
        by_loc[r.LocationID].append(r)

    features = []
    missing_coords: set = set()

    for loc_id, recs in sorted(by_loc.items()):
        if loc_id not in coords:
            missing_coords.add(loc_id)
            qa.add(
                SEV_WARNING, "missing_coords",
                f"Location {loc_id!r} has no coordinates; skipped.",
            )
            continue

        x, y = coords[loc_id]

        # Use the latest record per analyte (sort by SampleDate ascending; last wins)
        by_analyte: Dict[str, AnalyticalResultRecord] = {}
        for r in sorted(recs, key=lambda r: r.SampleDate or date.min):
            by_analyte[r.AnalyteCanonicalName] = r

        props: dict = {
            "location_id": loc_id,
            "site_id": recs[0].SiteID,
        }
        for analyte, r in sorted(by_analyte.items()):
            safe_key = analyte.replace(" ", "_").replace(",", "").replace("/", "_")
            props[f"{safe_key}_value"] = r.DisplayText or ""
            props[f"{safe_key}_exceeds"] = (
                bool(r.ExceedsScreeningLevel)
                if r.ExceedsScreeningLevel is not None
                else None
            )
            props[f"{safe_key}_date"] = (
                r.SampleDate.isoformat() if r.SampleDate else ""
            )

        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [x, y]},
            "properties": props,
        })

    qa.add(
        SEV_INFO, "export_geojson_complete",
        f"build_geojson: {len(features)} features from {len(by_loc)} locations; "
        f"{len(missing_coords)} location(s) skipped (no coords)",
    )
    return {"type": "FeatureCollection", "features": features}
```

**Steps:**
- [ ] Create module file as shown above
- [ ] Run `python -m pytest tests/test_export_geojson.py -q` — expect all pass

---

### Task 3: Wire CLI command in `autogis/adapters/cli.py`

**Files:**
- Modify: `autogis/adapters/cli.py`

**Complete command code:**

```python
@envmon.command("export-geojson")
@click.option("--results-csv", required=True, type=click.Path(exists=True),
              help="CSV of AnalyticalResultRecord rows (from import-edd --output-csv).")
@click.option("--coords-csv", required=True, type=click.Path(exists=True),
              help="CSV with columns: location_id, x, y")
@click.option("--output", required=True, type=click.Path(),
              help="Output GeoJSON file path (e.g. results.geojson).")
@click.option("--indent", type=int, default=2, show_default=True,
              help="JSON indent level (0 = compact).")
@click.option("--report", default=None, type=click.Path(),
              help="Optional QA report output path.")
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error",
              show_default=True)
def export_geojson_cmd(results_csv, coords_csv, output, indent, report, fail_on):
    """Tool 10.3: export analytical results to GeoJSON FeatureCollection (headless)."""
    import json as _json
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.export_geojson import build_geojson, load_well_coords
    from autogis.core.envmon.evaluate_rpd_qa import read_records_csv
    from autogis.core.envmon.gdb_schema import AnalyticalResultRecord

    results = read_records_csv(Path(results_csv), AnalyticalResultRecord)
    coords = load_well_coords(Path(coords_csv))
    qa = QACollector()
    fc = build_geojson(results, coords, qa=qa)

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_json.dumps(fc, indent=indent or None), encoding="utf-8")
    click.echo(f"Written: {out}  ({len(fc['features'])} feature(s))")
    _render_qa(qa, report, fail_on)
```

**Steps:**
- [ ] Add command to `autogis/adapters/cli.py`
- [ ] Add `"export-geojson": Runtime.CLOUD` to `TOOLS` dict in `autogis/runtime/capabilities.py`
- [ ] Run `python -m pytest -q` — expect all pass
- [ ] Commit: `feat(envmon): export-geojson — analytical results to GeoJSON FeatureCollection (Tool 10.3)`

---

## Run commands

```bash
# TDD step 1: verify tests fail before module exists
python -m pytest tests/test_export_geojson.py -q

# TDD step 2: after creating export_geojson.py
python -m pytest tests/test_export_geojson.py -q

# TDD step 3: full suite
python -m pytest -q
```
