# ImportFieldBoringLogs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `ImportFieldBoringLogs` — parse boring log CSV/XLSX (structured
field sheets or Survey123 export) into the 7 boring tables added in Phase 1.4:
`BoringLocations`, `LithologyIntervals`, `BoringSamples`, `WellConstruction`,
`GroundwaterObservations`, `BoringPhotos`, `BoringComments`.

**Architecture:**
- New: `autogis/core/envmon/import_boring_logs.py`
- Modify: `autogis/adapters/cli.py` — add `import-boring-logs` command (LOCAL)
- New: `tests/envmon/test_import_boring_logs.py`

## Global Constraints

- Branch: `feat/gdb-schema-upgrade`
- CSV parsing layer is arcpy-free and fully testable.
- GDB write is LOCAL (`# pragma: no cover`).
- Input: a directory containing `boring_locations.csv`, `lithology.csv`, `samples.csv`
  (the multi-sheet structure from field log CSV export). Also accepts a single XLSX workbook
  where sheet names match table names.
- Run tests with `python -m pytest -q`.

---

### Task 1: `import_boring_logs.py` — parse layer + tests

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_import_boring_logs.py`:

```python
import csv
from pathlib import Path
from autogis.core.envmon.import_boring_logs import (
    BoringLocation, LithologyInterval, BoringSample,
    parse_boring_locations_csv, parse_lithology_csv, parse_boring_samples_csv,
    validate_boring_package,
)
from autogis.core.common.qa import QACollector

_LOC_ROWS = [
    {"BoringID": "B-01", "SiteID": "H281", "LocationType": "Monitoring Well",
     "Northing": "4527893.12", "Easting": "293847.55",
     "GroundElevation_ft": "512.34", "Status": "Complete"},
]

_LITH_ROWS = [
    {"BoringID": "B-01", "TopDepth_ft": "0.0", "BottomDepth_ft": "5.0",
     "USCS": "SM", "PrimaryMaterial": "Sandy loam", "Color": "Brown",
     "Moisture": "Moist", "Description": "Fill"},
    {"BoringID": "B-01", "TopDepth_ft": "5.0", "BottomDepth_ft": "12.0",
     "USCS": "CL", "PrimaryMaterial": "Clay", "Color": "Gray",
     "Moisture": "Wet", "Description": "Native"},
]

_SAMP_ROWS = [
    {"SampleID": "B-01-S1", "BoringID": "B-01", "SampleType": "Soil",
     "TopDepth_ft": "3.0", "BottomDepth_ft": "4.5", "Matrix": "SOIL"},
]


def _write(tmp_path, fname, rows):
    p = tmp_path / fname
    with p.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return p


def test_parse_boring_locations(tmp_path):
    p = _write(tmp_path, "boring_locations.csv", _LOC_ROWS)
    locs = parse_boring_locations_csv(p)
    assert len(locs) == 1
    assert locs[0].boring_id == "B-01"


def test_parse_lithology(tmp_path):
    p = _write(tmp_path, "lithology.csv", _LITH_ROWS)
    ivals = parse_lithology_csv(p)
    assert len(ivals) == 2
    assert ivals[0].top_depth_ft == 0.0
    assert ivals[1].bottom_depth_ft == 12.0


def test_parse_boring_samples(tmp_path):
    p = _write(tmp_path, "samples.csv", _SAMP_ROWS)
    samps = parse_boring_samples_csv(p)
    assert len(samps) == 1
    assert samps[0].sample_id == "B-01-S1"


def test_validate_package_missing_boring_in_lithology(tmp_path):
    lp = _write(tmp_path, "boring_locations.csv", _LOC_ROWS)
    lith_bad = [{"BoringID": "B-99", **{k: v for k, v in _LITH_ROWS[0].items() if k != "BoringID"}}]
    lith_p = _write(tmp_path, "lithology.csv", lith_bad)
    locs = parse_boring_locations_csv(lp)
    ivals = parse_lithology_csv(lith_p)
    qa = QACollector()
    validate_boring_package(locs, ivals, [], qa)
    assert any(r.category == "lithology_boring_not_in_locations" for r in qa.records)


def test_validate_package_overlapping_intervals(tmp_path):
    overlap = [
        {"BoringID": "B-01", "TopDepth_ft": "0.0", "BottomDepth_ft": "6.0",
         "USCS": "SM", "PrimaryMaterial": "Sandy loam", "Color": "Brown",
         "Moisture": "Moist", "Description": ""},
        {"BoringID": "B-01", "TopDepth_ft": "5.0", "BottomDepth_ft": "12.0",
         "USCS": "CL", "PrimaryMaterial": "Clay", "Color": "Gray",
         "Moisture": "Wet", "Description": ""},
    ]
    lp = _write(tmp_path, "loc.csv", _LOC_ROWS)
    lith_p = _write(tmp_path, "lith.csv", overlap)
    locs = parse_boring_locations_csv(lp)
    ivals = parse_lithology_csv(lith_p)
    qa = QACollector()
    validate_boring_package(locs, ivals, [], qa)
    assert any(r.category == "overlapping_intervals" for r in qa.records)
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_import_boring_logs.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/import_boring_logs.py`**

```python
"""import_boring_logs.py — parse boring log CSV → boring GDB tables (arcpy-free parse).

GDB write (import_boring_package) is LOCAL (arcpy), # pragma: no cover.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, QARecord, SEV_ERROR, SEV_WARNING, SEV_INFO


@dataclass
class BoringLocation:
    boring_id: str
    site_id: str
    location_type: str = ""
    northing: Optional[float] = None
    easting: Optional[float] = None
    ground_elevation_ft: Optional[float] = None
    status: str = ""


@dataclass
class LithologyInterval:
    boring_id: str
    top_depth_ft: float
    bottom_depth_ft: float
    uscs: str = ""
    primary_material: str = ""
    color: str = ""
    moisture: str = ""
    description: str = ""


@dataclass
class BoringSample:
    sample_id: str
    boring_id: str
    sample_type: str = ""
    top_depth_ft: Optional[float] = None
    bottom_depth_ft: Optional[float] = None
    matrix: str = ""


def _f(row, key, default=None):
    v = row.get(key, "").strip()
    if not v:
        return default
    try:
        return float(v)
    except ValueError:
        return default


def parse_boring_locations_csv(path: Path) -> list[BoringLocation]:
    out = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.append(BoringLocation(
                boring_id=row.get("BoringID", "").strip(),
                site_id=row.get("SiteID", "").strip(),
                location_type=row.get("LocationType", ""),
                northing=_f(row, "Northing"),
                easting=_f(row, "Easting"),
                ground_elevation_ft=_f(row, "GroundElevation_ft"),
                status=row.get("Status", ""),
            ))
    return out


def parse_lithology_csv(path: Path) -> list[LithologyInterval]:
    out = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            top = _f(row, "TopDepth_ft")
            bot = _f(row, "BottomDepth_ft")
            if top is None or bot is None:
                continue
            out.append(LithologyInterval(
                boring_id=row.get("BoringID", "").strip(),
                top_depth_ft=top, bottom_depth_ft=bot,
                uscs=row.get("USCS", ""),
                primary_material=row.get("PrimaryMaterial", ""),
                color=row.get("Color", ""),
                moisture=row.get("Moisture", ""),
                description=row.get("Description", ""),
            ))
    return out


def parse_boring_samples_csv(path: Path) -> list[BoringSample]:
    out = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.append(BoringSample(
                sample_id=row.get("SampleID", "").strip(),
                boring_id=row.get("BoringID", "").strip(),
                sample_type=row.get("SampleType", ""),
                top_depth_ft=_f(row, "TopDepth_ft"),
                bottom_depth_ft=_f(row, "BottomDepth_ft"),
                matrix=row.get("Matrix", ""),
            ))
    return out


def validate_boring_package(
    locs: list[BoringLocation],
    intervals: list[LithologyInterval],
    samples: list[BoringSample],
    qa: QACollector,
) -> None:
    known_boring_ids = {loc.boring_id for loc in locs}

    # Lithology borings reference check
    for iv in intervals:
        if iv.boring_id not in known_boring_ids:
            qa.add(QARecord(SEV_WARNING, "lithology_boring_not_in_locations",
                            f"Lithology row references unknown boring {iv.boring_id!r}"))

    # Overlapping interval check (per boring)
    from collections import defaultdict
    by_boring: dict[str, list[LithologyInterval]] = defaultdict(list)
    for iv in intervals:
        by_boring[iv.boring_id].append(iv)
    for bid, ivs in by_boring.items():
        sorted_ivs = sorted(ivs, key=lambda x: x.top_depth_ft)
        for i in range(len(sorted_ivs) - 1):
            if sorted_ivs[i].bottom_depth_ft > sorted_ivs[i + 1].top_depth_ft:
                qa.add(QARecord(SEV_ERROR, "overlapping_intervals",
                                f"{bid}: interval {sorted_ivs[i].top_depth_ft}-"
                                f"{sorted_ivs[i].bottom_depth_ft} overlaps next"))

    qa.add(QARecord(SEV_INFO, "validation_complete",
                    f"Boring package: {len(locs)} locations, "
                    f"{len(intervals)} intervals, {len(samples)} samples."))


def import_boring_package(   # pragma: no cover
    gdb_path: str,
    locs: list[BoringLocation],
    intervals: list[LithologyInterval],
    samples: list[BoringSample],
) -> None:
    """Write boring package to GDB tables (ArcGIS Pro)."""
    import arcpy
    from pathlib import Path as _P
    from ...runtime.sessions import arcpy_env as _arcpy
    _ax = _arcpy()
    gdb = str(gdb_path)

    loc_table = str(_P(gdb) / "BoringLocations")
    if _ax.Exists(loc_table):
        with _ax.da.InsertCursor(loc_table,
                                 ["BoringID", "SiteID", "LocationType",
                                  "Northing", "Easting", "GroundElevation_ft",
                                  "Status"]) as cur:
            for loc in locs:
                cur.insertRow([loc.boring_id, loc.site_id, loc.location_type,
                               loc.northing, loc.easting, loc.ground_elevation_ft,
                               loc.status])

    lith_table = str(_P(gdb) / "LithologyIntervals")
    if _ax.Exists(lith_table):
        with _ax.da.InsertCursor(lith_table,
                                 ["BoringID", "TopDepth_ft", "BottomDepth_ft",
                                  "USCS", "PrimaryMaterial", "Color",
                                  "Moisture", "Description"]) as cur:
            for iv in intervals:
                cur.insertRow([iv.boring_id, iv.top_depth_ft, iv.bottom_depth_ft,
                               iv.uscs, iv.primary_material, iv.color,
                               iv.moisture, iv.description])
```

- [ ] **Step 4: Run tests + full suite + commit**

```bash
git add autogis/core/envmon/import_boring_logs.py tests/envmon/test_import_boring_logs.py
git commit -m "feat(envmon): import_boring_logs — BoringLocation, LithologyInterval, BoringSample parsers + QA"
```

---

### Task 2: CLI command `import-boring-logs`

```python
@envmon.command("import-boring-logs")
@click.argument("input_dir", type=click.Path(exists=True))
@click.option("--site", "site_id", required=True)
@click.option("--gdb", required=True, type=click.Path())
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def import_boring_logs_cmd(input_dir, site_id, gdb, report, fail_on):
    """Import boring log CSV package into GDB boring tables (ArcGIS Pro)."""
    _guard("import-boring-logs")
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.import_boring_logs import (
        parse_boring_locations_csv, parse_lithology_csv, parse_boring_samples_csv,
        validate_boring_package, import_boring_package)
    d = Path(input_dir)
    qa = QACollector()
    locs = parse_boring_locations_csv(d / "boring_locations.csv") if (d / "boring_locations.csv").exists() else []
    ivals = parse_lithology_csv(d / "lithology.csv") if (d / "lithology.csv").exists() else []
    samps = parse_boring_samples_csv(d / "samples.csv") if (d / "samples.csv").exists() else []
    validate_boring_package(locs, ivals, samps, qa)
    counts = qa.counts_by_severity()
    if counts.get("ERROR", 0) == 0:
        import_boring_package(gdb, locs, ivals, samps)
        click.echo(f"Imported: {len(locs)} borings, {len(ivals)} intervals, {len(samps)} samples.")
    _render_qa(qa, report, fail_on)
```

Commit:
```bash
git add autogis/adapters/cli.py tests/envmon/test_import_boring_logs.py
git commit -m "feat(cli): add import-boring-logs command (LOCAL, validates before writing)"
```
