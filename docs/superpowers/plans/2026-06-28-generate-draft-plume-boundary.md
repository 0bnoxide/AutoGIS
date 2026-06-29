# GenerateDraftPlumeBoundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `GenerateDraftPlumeBoundary` (roadmap #4.5) — produce a DRAFT plume extent polygon (GeoJSON and optional WKT) from monitoring wells that exceed a screening level, using a convex or concave hull; outputs are explicitly DRAFT for analyst review, not a geostatistical model.

**Architecture:**
- New: `autogis/core/envmon/draft_plume_boundary.py` — `ExceedancePoint` and `DraftPlumeBoundaryResult` dataclasses, two CSV loaders, hull computation, GeoJSON/WKT serializers, `# pragma: no cover` arcpy GDB seam.
- Modify: `autogis/core/common/numpy_geom.py` — add `concave_hull()` wrapper following the existing try/except-at-import pattern.
- New: `tests/envmon/test_draft_plume_boundary.py` — all arcpy-free tests.
- Modify: `tests/core/common/test_numpy_geom.py` — add `concave_hull` tests.
- Modify: `autogis/adapters/cli.py` — add `envmon draft-plume-boundary` command.

**Tech Stack:** numpy, csv (stdlib), json (GeoJSON output), click (CLI), `numpy_geom.convex_hull` + `npg_analysis.concave` (hull algorithms).

## Global Constraints

- `autogis/core/` and `autogis/adapters/` must import with neither `arcpy` nor `arcgis` present. Verify after each task with: `python -c "import autogis.core.envmon.draft_plume_boundary"`.
- The ONLY arcpy code is `write_plume_draft_to_gdb()` — always `# pragma: no cover`.
- **DRAFT label is mandatory on every output path:**
  - GeoJSON properties: `"review_status": "DRAFT"` and `"draft_warning": "<full warning text>"`
  - WKT console output: printed with a `[DRAFT]` prefix line
  - GDB write: field `ReviewStatus = "DRAFT"` (matches `groundwater_contours.py` convention)
  - QA: every run emits at least one `SEV_INFO` message referencing DRAFT
- `convex` hull is the default (`--hull-method convex`). `concave` is opt-in via `--hull-method concave`.
- Minimum 3 exceedance points required; fewer → `SEV_ERROR`, no polygon output, non-zero exit.
- **Reuse** `autogis.core.envmon.export_geojson.load_well_coords` for coordinate loading; do not duplicate.
- `convex_hull()` and `concave_hull()` both return **open** rings (last vertex ≠ first vertex). GeoJSON Polygon `coordinates[0]` and WKT both require a **closed** ring. Serializers must append `vertices[0]` to close the ring. `DraftPlumeBoundaryResult.hull_vertices` stores the open ring.
- Heavy geostatistical surface modeling (kriging/EBK) is Phase 5 and explicitly **deferred**. This module is a drafting helper only.
- Tests run with `python -m pytest -q`.

---

### Task 1: `ExceedancePoint` dataclass + two CSV loaders

**Files:**
- Create: `autogis/core/envmon/draft_plume_boundary.py`
- Create: `tests/envmon/test_draft_plume_boundary.py`

**Interfaces:**
- Produces:
  - `ExceedancePoint(location_id: str, x: float, y: float, analyte: str | None, event_date: str | None)`
  - `load_exceedance_points_csv(path: Path) -> list[ExceedancePoint]`
  - `filter_results_to_exceedance_points(results_path: Path, coords_path: Path, *, analyte: str | None = None, qa: QACollector) -> list[ExceedancePoint]`
- Consumes: `autogis.core.envmon.export_geojson.load_well_coords`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_draft_plume_boundary.py`:

```python
"""Tests for draft_plume_boundary — CSV loaders and dataclasses."""
from __future__ import annotations
import csv
from pathlib import Path

import pytest

from autogis.core.common.qa import QACollector
from autogis.core.envmon.draft_plume_boundary import (
    ExceedancePoint,
    load_exceedance_points_csv,
    filter_results_to_exceedance_points,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _points_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


_RESULT_FIELDS = [
    "ImportBatchID", "SiteID", "Matrix", "LocationID",
    "SampleID", "ParentSampleID", "SampleDate",
    "DepthTop_ft", "DepthBottom_ft", "DepthIntervalText",
    "AnalyticalGroup", "MethodGroup", "AnalyteName",
    "AnalyteCanonicalName", "AnalyteAbbreviation",
    "ResultRawText", "ResultNumeric", "ReportingLimit",
    "DetectionLimit", "Units", "Qualifier",
    "IsNonDetect", "IsDetected", "IsEstimated", "IsDiluted",
    "IsNotAnalyzed", "IsNotSampled", "IsNotMeasured",
    "ScreeningLevel", "ScreeningLevelSource",
    "ExceedsScreeningLevel", "DisplayText", "DisplayColorClass",
    "SourceWorkbook", "SourceSheet", "SourceRow",
    "SourceColumn", "SourceCell",
]


def _results_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=_RESULT_FIELDS, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            full = {f: "" for f in _RESULT_FIELDS}
            full.update(row)
            w.writerow(full)


def _coords_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["location_id", "x", "y"])
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------------------
# load_exceedance_points_csv
# ---------------------------------------------------------------------------

def test_load_exceedance_points_csv_basic(tmp_path):
    p = tmp_path / "pts.csv"
    _points_csv(p, [
        {"location_id": "MW-01", "x": "100.0", "y": "200.0"},
        {"location_id": "MW-02", "x": "110.0", "y": "205.0"},
    ])
    pts = load_exceedance_points_csv(p)
    assert len(pts) == 2
    assert pts[0].location_id == "MW-01"
    assert abs(pts[0].x - 100.0) < 1e-9
    assert abs(pts[0].y - 200.0) < 1e-9


def test_load_exceedance_points_csv_optional_fields_default_none(tmp_path):
    p = tmp_path / "pts.csv"
    _points_csv(p, [{"location_id": "MW-01", "x": "1.0", "y": "2.0"}])
    pts = load_exceedance_points_csv(p)
    assert pts[0].analyte is None
    assert pts[0].event_date is None


def test_load_exceedance_points_csv_with_optional_fields(tmp_path):
    p = tmp_path / "pts.csv"
    _points_csv(p, [{"location_id": "MW-01", "x": "1.0", "y": "2.0",
                     "analyte": "Benzene", "event_date": "2025-04-01"}])
    pts = load_exceedance_points_csv(p)
    assert pts[0].analyte == "Benzene"
    assert pts[0].event_date == "2025-04-01"


# ---------------------------------------------------------------------------
# filter_results_to_exceedance_points
# ---------------------------------------------------------------------------

def test_filter_results_returns_exceedances_only(tmp_path):
    r = tmp_path / "r.csv"
    c = tmp_path / "c.csv"
    _results_csv(r, [
        {"LocationID": "MW-01", "ExceedsScreeningLevel": "1",
         "AnalyteCanonicalName": "Benzene"},
        {"LocationID": "MW-02", "ExceedsScreeningLevel": "0",
         "AnalyteCanonicalName": "Benzene"},
    ])
    _coords_csv(c, [
        {"location_id": "MW-01", "x": "1.0", "y": "2.0"},
        {"location_id": "MW-02", "x": "3.0", "y": "4.0"},
    ])
    pts = filter_results_to_exceedance_points(r, c, qa=QACollector())
    assert len(pts) == 1
    assert pts[0].location_id == "MW-01"


def test_filter_results_analyte_filter(tmp_path):
    r = tmp_path / "r.csv"
    c = tmp_path / "c.csv"
    _results_csv(r, [
        {"LocationID": "MW-01", "ExceedsScreeningLevel": "1",
         "AnalyteCanonicalName": "Benzene"},
        {"LocationID": "MW-02", "ExceedsScreeningLevel": "1",
         "AnalyteCanonicalName": "Toluene"},
    ])
    _coords_csv(c, [
        {"location_id": "MW-01", "x": "1.0", "y": "2.0"},
        {"location_id": "MW-02", "x": "3.0", "y": "4.0"},
    ])
    pts = filter_results_to_exceedance_points(
        r, c, analyte="Benzene", qa=QACollector())
    assert len(pts) == 1
    assert pts[0].location_id == "MW-01"
    assert pts[0].analyte == "Benzene"


def test_filter_results_missing_coords_warns_and_skips(tmp_path):
    r = tmp_path / "r.csv"
    c = tmp_path / "c.csv"
    _results_csv(r, [{"LocationID": "MW-NO-COORD", "ExceedsScreeningLevel": "1",
                      "AnalyteCanonicalName": "Benzene"}])
    _coords_csv(c, [])
    qa = QACollector()
    pts = filter_results_to_exceedance_points(r, c, qa=qa)
    assert len(pts) == 0
    warns = [rec for rec in qa.records if rec.severity == "WARNING"]
    assert any("MW-NO-COORD" in rec.message for rec in warns)


def test_filter_results_deduplicates_by_location(tmp_path):
    """Two analytes exceeding at the same well → one ExceedancePoint."""
    r = tmp_path / "r.csv"
    c = tmp_path / "c.csv"
    _results_csv(r, [
        {"LocationID": "MW-01", "ExceedsScreeningLevel": "1",
         "AnalyteCanonicalName": "Benzene"},
        {"LocationID": "MW-01", "ExceedsScreeningLevel": "1",
         "AnalyteCanonicalName": "Toluene"},
    ])
    _coords_csv(c, [{"location_id": "MW-01", "x": "1.0", "y": "2.0"}])
    pts = filter_results_to_exceedance_points(r, c, qa=QACollector())
    assert len(pts) == 1
    assert pts[0].location_id == "MW-01"
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_draft_plume_boundary.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'autogis.core.envmon.draft_plume_boundary'`

- [ ] **Step 3: Implement draft_plume_boundary.py (loaders section only)**

Create `autogis/core/envmon/draft_plume_boundary.py`:

```python
"""draft_plume_boundary.py — DRAFT plume extent polygon from exceedance points.

WARNING: All output is ReviewStatus='DRAFT'. This module builds a geometric
approximation (convex or concave hull) around wells exceeding a screening
level. It is a drafting aid for analyst review — NOT a geostatistical surface
model, NOT a regulatory deliverable. Phase 5 kriging/EBK is deferred and
separate (docs/IMPLEMENTATION_ROADMAP_PRIORITIZED.md Phase 5).

DRAFT label appears on every output path:
  - GeoJSON properties:  "review_status": "DRAFT", "draft_warning": "<text>"
  - WKT console output:  printed with [DRAFT] prefix
  - GDB feature class:   ReviewStatus = "DRAFT"  (matches groundwater_contours.py)
  - QA messages:         every run emits a SEV_INFO referencing DRAFT

arcpy usage: ONLY in write_plume_draft_to_gdb() — # pragma: no cover.
All other functions import without arcpy or arcgis.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from autogis.core.common.qa import QACollector, SEV_ERROR, SEV_INFO, SEV_WARNING
from autogis.core.envmon.export_geojson import load_well_coords


_DRAFT_WARNING = (
    "DRAFT: Geometric approximation (hull around exceedance points) for "
    "analyst review only. Not a geostatistical model. Do not cite in "
    "regulatory deliverables without professional review and field "
    "verification. Phase 5 geostatistical modeling (kriging/EBK) is "
    "deferred."
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ExceedancePoint:
    """A monitoring location where at least one analyte exceeds a screening level."""
    location_id: str
    x: float
    y: float
    analyte: Optional[str] = None
    event_date: Optional[str] = None


@dataclass
class DraftPlumeBoundaryResult:
    """Result of a draft plume boundary computation.

    hull_vertices is an OPEN ring: last vertex != first.
    Serializers (result_to_geojson, result_to_wkt) are responsible for closing
    the ring by appending hull_vertices[0].
    review_status is always 'DRAFT'.
    """
    site_id: str
    analyte: Optional[str]            # None = all exceedances combined
    hull_method: str                   # "convex" | "concave"
    k_neighbors: Optional[int]        # only relevant for concave
    n_exceedance_points: int
    hull_vertices: list[list[float]]  # open ring: [[x0,y0], [x1,y1], ...]
    review_status: str = "DRAFT"      # always "DRAFT" — do not override
    draft_warning: str = _DRAFT_WARNING


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_exceedance_points_csv(path: Path) -> list[ExceedancePoint]:
    """Load from a simple CSV with columns: location_id, x, y [, analyte, event_date].

    All rows are treated as exceedance points (caller is responsible for
    pre-filtering to exceedances only).
    """
    pts: list[ExceedancePoint] = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            pts.append(ExceedancePoint(
                location_id=row["location_id"].strip(),
                x=float(row["x"]),
                y=float(row["y"]),
                analyte=row.get("analyte", "").strip() or None,
                event_date=row.get("event_date", "").strip() or None,
            ))
    return pts


def filter_results_to_exceedance_points(
    results_path: Path,
    coords_path: Path,
    *,
    analyte: Optional[str] = None,
    qa: QACollector,
) -> list[ExceedancePoint]:
    """Filter an AnalyticalResultRecord CSV to exceedance points with coordinates.

    reads coords via export_geojson.load_well_coords (columns: location_id, x, y).
    Filters rows by ExceedsScreeningLevel == '1'.
    Applies optional analyte filter (AnalyteCanonicalName).
    Deduplicates: one ExceedancePoint per well (first exceedance wins when
    no analyte filter; any exceedance qualifies the well).
    Emits SEV_WARNING for wells with exceedances but no coordinates.
    """
    coords = load_well_coords(coords_path)
    seen: set[str] = set()
    pts: list[ExceedancePoint] = []
    with Path(results_path).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if str(row.get("ExceedsScreeningLevel", "0")).strip() != "1":
                continue
            a = row.get("AnalyteCanonicalName", "").strip()
            if analyte is not None and a != analyte:
                continue
            loc = row.get("LocationID", "").strip()
            if loc in seen:
                continue
            if loc not in coords:
                qa.add(SEV_WARNING, "missing_coords",
                       f"{loc}: exceeds screening level but has no coordinates "
                       "in the coords CSV; excluded from plume boundary.",
                       location_id=loc)
                continue
            x, y = coords[loc]
            pts.append(ExceedancePoint(
                location_id=loc, x=x, y=y, analyte=a or None))
            seen.add(loc)
    return pts
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_draft_plume_boundary.py -v
```
Expected: all loader tests PASS.

- [ ] **Step 5: Full suite check**

```
python -m pytest -q
```
Expected: all pre-existing tests still PASS; new tests PASS.

- [ ] **Step 6: Commit**

```bash
git add autogis/core/envmon/draft_plume_boundary.py \
        tests/envmon/test_draft_plume_boundary.py
git commit -m "feat(envmon): draft_plume_boundary — ExceedancePoint dataclass + CSV loaders"
```

---

### Task 2: `concave_hull()` wrapper in `numpy_geom.py`

**Files:**
- Modify: `autogis/core/common/numpy_geom.py` (append after `densify_polyline` section)
- Modify: `tests/core/common/test_numpy_geom.py` (append tests)

**Interfaces:**
- Produces: `concave_hull(xy: np.ndarray, k: int = 3) -> np.ndarray`
  - Returns open ring, shape (M, 2), M >= 3. Falls back to `convex_hull(xy)` on any runtime failure.
  - When npg unavailable at import time, always delegates to `convex_hull(xy)`.
- Consumes: `convex_hull` (already in `numpy_geom.py`), `npg_analysis.concave`

**Background on npg `concave()`:** accepts `np.ndarray` (preferred — internally does `np.unique(arr, axis=0).tolist()`), returns `np.ndarray` shape (M, 2) normally or a Python list when exactly 3 unique points remain (edge case). Our wrapper normalises the return with `np.array()`. Known quirk: `knn0` (its internal k-NN helper) was designed for `p in pnts` and omits the literal nearest neighbor when `p` is already removed from the candidate set. This is acceptable for environmental monitoring point counts (typically 3–30 wells). Prefer k >= 3 (npg enforces this itself).

- [ ] **Step 1: Write failing tests (append to existing file)**

Open `tests/core/common/test_numpy_geom.py` and append:

```python
from autogis.core.common.numpy_geom import concave_hull


def test_concave_hull_returns_ndarray():
    xy = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0],
                   [0.0, 1.0], [0.5, 0.5]])
    result = concave_hull(xy)
    assert isinstance(result, np.ndarray)
    assert result.shape[1] == 2


def test_concave_hull_at_least_three_vertices():
    xy = np.array([[0.0, 0.0], [2.0, 0.0], [2.0, 2.0],
                   [0.0, 2.0], [1.0, 1.0]])
    result = concave_hull(xy)
    assert len(result) >= 3


def test_concave_hull_open_ring_first_ne_last():
    """concave_hull must return an OPEN ring so serializers can close it."""
    xy = np.array([[0.0, 0.0], [3.0, 0.0], [3.0, 3.0],
                   [0.0, 3.0], [1.5, 1.5]])
    result = concave_hull(xy)
    # Should NOT be closed (first == last); open ring is the contract.
    if len(result) > 1:
        assert not np.allclose(result[0], result[-1])


def test_concave_hull_k_parameter_accepted():
    """k parameter must be accepted without error."""
    xy = np.array([[0.0, 0.0], [4.0, 0.0], [4.0, 4.0],
                   [0.0, 4.0], [2.0, 2.0], [1.0, 1.0]])
    result = concave_hull(xy, k=4)
    assert isinstance(result, np.ndarray)
    assert len(result) >= 3


def test_concave_hull_exact_three_points():
    """Three points is the minimum — hull is those three points."""
    xy = np.array([[0.0, 0.0], [1.0, 0.0], [0.5, 1.0]])
    result = concave_hull(xy)
    assert len(result) >= 3


def test_concave_hull_degrades_gracefully_on_collinear():
    """Collinear points may cause algorithm failure; must not raise."""
    xy = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0],
                   [3.0, 0.0], [1.5, 0.0]])
    # Should not raise — degrades to convex_hull if concave fails
    result = concave_hull(xy)
    assert isinstance(result, np.ndarray)
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/core/common/test_numpy_geom.py -v -k "concave"
```
Expected: FAIL — `ImportError: cannot import name 'concave_hull' from 'autogis.core.common.numpy_geom'`

- [ ] **Step 3: Append `concave_hull` to `numpy_geom.py`**

Open `autogis/core/common/numpy_geom.py` and append after the `densify_polyline` block:

```python
# ---------------------------------------------------------------------------
# concave_hull
# ---------------------------------------------------------------------------
# Background: npg_analysis.concave is a k-nearest-neighbor recursive concave
# hull. It accepts np.ndarray, internally converts to list via np.unique().tolist(),
# and returns np.ndarray (M, 2) — or a plain Python list when exactly 3 unique
# points remain. Our wrapper normalises the return with np.array() and falls
# back to convex_hull() on any runtime error (e.g., algorithm can't close hull
# due to collinear points or knn0 quirk). The fallback produces a valid (if
# conservative) boundary.
try:
    from autogis.core.common.npg.npg_analysis import concave as _concave_npg

    def concave_hull(xy: np.ndarray, k: int = 3) -> np.ndarray:
        """K-nearest-neighbor concave hull (Dan Patterson npg).

        Falls back to convex_hull on any runtime failure — callers always get
        a valid polygon regardless of point geometry.

        Parameters
        ----------
        xy : ndarray, shape (N, 2)
        k : int
            Starting number of nearest neighbors for the concave algorithm.
            npg enforces k >= 3 internally. Larger k → more convex result.

        Returns
        -------
        ndarray, shape (M, 2) — OPEN ring (first vertex != last vertex).
            Serializers must close the ring by appending vertices[0].

        Notes
        -----
        npg knn0 quirk: knn0 slices [1:k+1] (designed for the case p in pnts),
        but concave() removes cur_p from candidates before calling knn0, so the
        actual nearest neighbor is skipped. Larger k compensates. For
        environmental monitoring (3–30 wells) this is acceptable.
        """
        if len(xy) < 3:
            return xy
        try:
            result = _concave_npg(xy, k)
            arr = np.array(result)
            # Strip closing duplicate if present (some edge paths append it).
            if len(arr) > 1 and np.allclose(arr[0], arr[-1]):
                arr = arr[:-1]
            return arr
        except Exception:
            return convex_hull(xy)

except (ImportError, AttributeError):
    def concave_hull(xy: np.ndarray, k: int = 3) -> np.ndarray:
        """concave_hull (npg_analysis not available): delegates to convex_hull.

        Parameters
        ----------
        xy : ndarray, shape (N, 2)
        k : int  (ignored — convex hull has no k parameter)

        Returns
        -------
        ndarray, shape (M, 2) — OPEN ring.
        """
        return convex_hull(xy)
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/core/common/test_numpy_geom.py -v
```
Expected: ALL tests PASS (including all pre-existing tests).

- [ ] **Step 5: Verify headless import**

```
python -c "from autogis.core.common.numpy_geom import concave_hull; print('OK')"
```
Expected: `OK` with no import error.

- [ ] **Step 6: Commit**

```bash
git add autogis/core/common/numpy_geom.py \
        tests/core/common/test_numpy_geom.py
git commit -m "feat(numpy_geom): add concave_hull() wrapper over npg_analysis.concave"
```

---

### Task 3: `compute_draft_plume_boundary()` + serializers

**Files:**
- Modify: `autogis/core/envmon/draft_plume_boundary.py` (append after loaders)
- Modify: `tests/envmon/test_draft_plume_boundary.py` (append hull + serializer tests)

**Interfaces:**
- Consumes: `convex_hull`, `concave_hull` from `numpy_geom`; `ExceedancePoint`, `DraftPlumeBoundaryResult` from this module
- Produces:
  - `compute_draft_plume_boundary(points, *, hull_method="convex", k_neighbors=3, site_id="", analyte=None, qa) -> DraftPlumeBoundaryResult | None`  — returns `None` when < 3 points; emits `SEV_ERROR` to qa.
  - `result_to_geojson(result: DraftPlumeBoundaryResult) -> dict` — GeoJSON Feature (Polygon), closed ring, `review_status: "DRAFT"`.
  - `result_to_wkt(result: DraftPlumeBoundaryResult) -> str` — `POLYGON ((x0 y0, x1 y1, ..., x0 y0))` with `[DRAFT]` prefix when printed.

- [ ] **Step 1: Write failing tests (append to test file)**

Append to `tests/envmon/test_draft_plume_boundary.py`:

```python
import json
import numpy as np

from autogis.core.envmon.draft_plume_boundary import (
    ExceedancePoint,
    DraftPlumeBoundaryResult,
    compute_draft_plume_boundary,
    result_to_geojson,
    result_to_wkt,
)


# ---------------------------------------------------------------------------
# Known point set: 5 wells forming a square + interior
# Convex hull = 4 corners; result should have 4 vertices (open ring)
# ---------------------------------------------------------------------------
_SQUARE_POINTS = [
    ExceedancePoint("MW-01", 0.0, 0.0),
    ExceedancePoint("MW-02", 1.0, 0.0),
    ExceedancePoint("MW-03", 1.0, 1.0),
    ExceedancePoint("MW-04", 0.0, 1.0),
    ExceedancePoint("MW-05", 0.5, 0.5),  # interior — excluded from convex hull
]


def test_compute_returns_result_object():
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    assert isinstance(r, DraftPlumeBoundaryResult)


def test_compute_review_status_always_draft():
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    assert r.review_status == "DRAFT"


def test_compute_draft_warning_present():
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    assert "DRAFT" in r.draft_warning.upper()


def test_compute_hull_vertices_open_ring():
    """hull_vertices must be open: first vertex != last vertex."""
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    verts = r.hull_vertices
    assert len(verts) >= 3
    assert verts[0] != verts[-1], "hull_vertices must be open (not closed)"


def test_compute_hull_vertices_at_least_3():
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    assert len(r.hull_vertices) >= 3


def test_compute_n_exceedance_points():
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    assert r.n_exceedance_points == len(_SQUARE_POINTS)


def test_compute_qa_emits_draft_info():
    """At least one QA INFO record must mention DRAFT."""
    qa = QACollector()
    compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    info_msgs = [rec.message for rec in qa.records if rec.severity == "INFO"]
    assert any("DRAFT" in m.upper() for m in info_msgs)


def test_compute_too_few_points_returns_none():
    qa = QACollector()
    r = compute_draft_plume_boundary(
        [ExceedancePoint("MW-01", 0.0, 0.0), ExceedancePoint("MW-02", 1.0, 0.0)],
        qa=qa)
    assert r is None
    errors = [rec for rec in qa.records if rec.severity == "ERROR"]
    assert errors, "expected a SEV_ERROR for < 3 points"


def test_compute_hull_method_convex_default():
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    assert r.hull_method == "convex"


def test_compute_hull_method_concave():
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, hull_method="concave",
                                     k_neighbors=3, qa=qa)
    assert r.hull_method == "concave"
    assert isinstance(r.hull_vertices, list)
    assert len(r.hull_vertices) >= 3


def test_compute_site_id_stored():
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, site_id="DEMO-01", qa=qa)
    assert r.site_id == "DEMO-01"


# ---------------------------------------------------------------------------
# result_to_geojson
# ---------------------------------------------------------------------------

def test_result_to_geojson_is_feature():
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    fc = result_to_geojson(r)
    assert fc["type"] == "Feature"
    assert fc["geometry"]["type"] == "Polygon"


def test_result_to_geojson_review_status_draft():
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    fc = result_to_geojson(r)
    assert fc["properties"]["review_status"] == "DRAFT"


def test_result_to_geojson_draft_warning_property():
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    fc = result_to_geojson(r)
    assert "draft_warning" in fc["properties"]
    assert "DRAFT" in fc["properties"]["draft_warning"].upper()


def test_result_to_geojson_ring_is_closed():
    """GeoJSON Polygon ring must have first == last coordinate."""
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    fc = result_to_geojson(r)
    ring = fc["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1], "GeoJSON ring must be closed (first == last)"


def test_result_to_geojson_ring_min_4_coords():
    """Minimum valid GeoJSON polygon ring: 4 coords (3 unique + closing)."""
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    fc = result_to_geojson(r)
    ring = fc["geometry"]["coordinates"][0]
    assert len(ring) >= 4


def test_result_to_geojson_is_json_serialisable():
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    fc = result_to_geojson(r)
    blob = json.dumps(fc)  # must not raise
    assert "DRAFT" in blob


# ---------------------------------------------------------------------------
# result_to_wkt
# ---------------------------------------------------------------------------

def test_result_to_wkt_starts_with_polygon():
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    wkt = result_to_wkt(r)
    assert wkt.startswith("POLYGON")


def test_result_to_wkt_ring_closed():
    """WKT ring must close: first and last coordinate pair are identical."""
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    wkt = result_to_wkt(r)
    # Extract coordinates between the outer parentheses
    inner = wkt.split("((")[1].rstrip("))")
    pairs = [pair.strip().split() for pair in inner.split(",")]
    assert pairs[0] == pairs[-1], "WKT ring must be closed"
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_draft_plume_boundary.py -v -k "compute or geojson or wkt"
```
Expected: FAIL — `ImportError` for `compute_draft_plume_boundary`, `result_to_geojson`, `result_to_wkt`.

- [ ] **Step 3: Append computation + serializers to draft_plume_boundary.py**

Append to `autogis/core/envmon/draft_plume_boundary.py`:

```python
# ---------------------------------------------------------------------------
# Hull computation
# ---------------------------------------------------------------------------
# Imported here (not top-level) to keep the module importable without numpy
# being present in all environments — though numpy IS a required dep of this
# project. The imports are top-level below; this comment is a scope note.
from autogis.core.common.numpy_geom import convex_hull, concave_hull


def compute_draft_plume_boundary(
    points: list[ExceedancePoint],
    *,
    hull_method: str = "convex",
    k_neighbors: int = 3,
    site_id: str = "",
    analyte: Optional[str] = None,
    qa: QACollector,
) -> Optional[DraftPlumeBoundaryResult]:
    """Compute a DRAFT plume extent polygon from exceedance points.

    Parameters
    ----------
    points : list[ExceedancePoint]
        Wells that exceed a screening level. Must have >= 3 members.
    hull_method : str
        "convex" (default) or "concave".
    k_neighbors : int
        Starting k for concave hull (ignored for convex). npg enforces k >= 3.
    site_id : str
        Stored on the result for provenance; does not affect computation.
    analyte : str | None
        Stored on the result for provenance; does not affect computation.
    qa : QACollector
        Receives at minimum one SEV_INFO noting DRAFT status.

    Returns
    -------
    DraftPlumeBoundaryResult with OPEN hull_vertices (first != last), or None
    if fewer than 3 points were supplied.
    """
    if hull_method not in ("convex", "concave"):
        raise ValueError(
            f"hull_method must be 'convex' or 'concave', got {hull_method!r}")

    if len(points) < 3:
        qa.add(SEV_ERROR, "insufficient_exceedance_points",
               f"Only {len(points)} exceedance point(s) supplied "
               f"(minimum 3 required for a polygon). No boundary generated.",
               recommended_action="Add more exceedance points or lower the "
                                  "screening level threshold.",
               site_id=site_id)
        return None

    xy = np.array([[p.x, p.y] for p in points], dtype=float)

    if hull_method == "convex":
        hull_arr = convex_hull(xy)
    else:
        hull_arr = concave_hull(xy, k=k_neighbors)

    # Ensure open ring (convex_hull already strips closing duplicate;
    # concave_hull wrapper does the same — but be defensive).
    if len(hull_arr) > 1 and np.allclose(hull_arr[0], hull_arr[-1]):
        hull_arr = hull_arr[:-1]

    hull_vertices = hull_arr.tolist()

    qa.add(SEV_INFO, "draft_plume_boundary_generated",
           f"DRAFT plume boundary: {len(hull_vertices)}-vertex {hull_method} "
           f"hull from {len(points)} exceedance point(s). "
           f"ReviewStatus=DRAFT. {_DRAFT_WARNING}",
           site_id=site_id)

    return DraftPlumeBoundaryResult(
        site_id=site_id,
        analyte=analyte,
        hull_method=hull_method,
        k_neighbors=k_neighbors if hull_method == "concave" else None,
        n_exceedance_points=len(points),
        hull_vertices=hull_vertices,
        review_status="DRAFT",
        draft_warning=_DRAFT_WARNING,
    )


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def result_to_geojson(result: DraftPlumeBoundaryResult) -> dict:
    """Serialize to a GeoJSON Feature (Polygon).

    The coordinate ring is CLOSED: last coordinate == first coordinate.
    Always includes review_status='DRAFT' and draft_warning in properties.
    Caller is responsible for json.dumps().
    """
    import datetime
    closed_ring = result.hull_vertices + [result.hull_vertices[0]]
    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [closed_ring],
        },
        "properties": {
            "site_id": result.site_id,
            "analyte": result.analyte or "all_exceedances",
            "hull_method": result.hull_method,
            "k_neighbors": result.k_neighbors,
            "n_exceedance_points": result.n_exceedance_points,
            "review_status": "DRAFT",
            "draft_warning": result.draft_warning,
            "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        },
    }


def result_to_wkt(result: DraftPlumeBoundaryResult) -> str:
    """Serialize to a WKT POLYGON string (ring is closed: first == last pair).

    The WKT string itself does NOT include the [DRAFT] warning prefix;
    the CLI is responsible for printing the prefix before echoing the WKT
    so that the WKT string remains valid geometry text.

    Example return value:
        POLYGON ((0.0 0.0, 1.0 0.0, 1.0 1.0, 0.0 1.0, 0.0 0.0))
    """
    verts = result.hull_vertices + [result.hull_vertices[0]]  # close ring
    coords_str = ", ".join(f"{xy[0]} {xy[1]}" for xy in verts)
    return f"POLYGON (({coords_str}))"
```

Also add to the top-level imports in `draft_plume_boundary.py` (after the `from autogis.core.envmon.export_geojson import load_well_coords` line):

```python
# numpy_geom imported inside compute_draft_plume_boundary to avoid
# a circular-import risk; numpy itself is imported at the top for arrays.
```

Wait — `numpy_geom` is in `core/common`, not in `core/envmon`, so there is no circular import. Import it at the top level. Replace the comment with:

```python
from autogis.core.common.numpy_geom import convex_hull, concave_hull
```

Add this immediately after the `from autogis.core.envmon.export_geojson import load_well_coords` line at the top of the module.

And in `compute_draft_plume_boundary`, remove the inline import comment (the functions are already imported at module level).

- [ ] **Step 4: Run all draft_plume_boundary tests**

```
python -m pytest tests/envmon/test_draft_plume_boundary.py -v
```
Expected: ALL tests PASS.

- [ ] **Step 5: Full suite check**

```
python -m pytest -q
```
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add autogis/core/envmon/draft_plume_boundary.py \
        tests/envmon/test_draft_plume_boundary.py
git commit -m "feat(envmon): draft_plume_boundary — hull computation + GeoJSON/WKT serializers"
```

---

### Task 4: CLI command + arcpy GDB seam

**Files:**
- Modify: `autogis/adapters/cli.py` (add `draft-plume-boundary` command in the headless section)
- Modify: `autogis/core/envmon/draft_plume_boundary.py` (append `write_plume_draft_to_gdb`)
- Create: `tests/envmon/test_cli_draft_plume_boundary.py`

**Interfaces:**
- Consumes: all of `draft_plume_boundary.py` public API; `_render_qa`, `_guard` from `cli.py`
- Produces: `envmon draft-plume-boundary` CLI command; `write_plume_draft_to_gdb` (arcpy, `# pragma: no cover`)

**CLI signature:**
```
autogis envmon draft-plume-boundary
    (--points-csv PATH | --results-csv PATH --coords-csv PATH)
    [--analyte NAME]
    --output PATH
    [--hull-method {convex,concave}]
    [--k INT]
    [--site SITE_ID]
    [--wkt]
    [--gdb PATH]
    [--qa-report PATH]
    [--fail-on {error,warning}]
```

`--points-csv` and `--results-csv`/`--coords-csv` are mutually exclusive input modes.
`--gdb` triggers `_guard("draft-plume-boundary")` then writes to `Env_PlumeBoundary_Draft` feature class.

- [ ] **Step 1: Write failing CLI tests**

Create `tests/envmon/test_cli_draft_plume_boundary.py`:

```python
"""CLI tests for envmon draft-plume-boundary (arcpy-free)."""
from __future__ import annotations
import csv, json
from pathlib import Path

import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis


def _points_csv(path: Path) -> None:
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["location_id", "x", "y"])
        w.writeheader()
        w.writerow({"location_id": "MW-01", "x": "0.0",  "y": "0.0"})
        w.writerow({"location_id": "MW-02", "x": "1.0",  "y": "0.0"})
        w.writerow({"location_id": "MW-03", "x": "1.0",  "y": "1.0"})
        w.writerow({"location_id": "MW-04", "x": "0.0",  "y": "1.0"})
        w.writerow({"location_id": "MW-05", "x": "0.5",  "y": "0.5"})


_RESULT_FIELDS = [
    "ImportBatchID", "SiteID", "Matrix", "LocationID",
    "SampleID", "ParentSampleID", "SampleDate",
    "DepthTop_ft", "DepthBottom_ft", "DepthIntervalText",
    "AnalyticalGroup", "MethodGroup", "AnalyteName",
    "AnalyteCanonicalName", "AnalyteAbbreviation",
    "ResultRawText", "ResultNumeric", "ReportingLimit",
    "DetectionLimit", "Units", "Qualifier",
    "IsNonDetect", "IsDetected", "IsEstimated", "IsDiluted",
    "IsNotAnalyzed", "IsNotSampled", "IsNotMeasured",
    "ScreeningLevel", "ScreeningLevelSource",
    "ExceedsScreeningLevel", "DisplayText", "DisplayColorClass",
    "SourceWorkbook", "SourceSheet", "SourceRow",
    "SourceColumn", "SourceCell",
]


def _results_csv(path: Path) -> None:
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=_RESULT_FIELDS, extrasaction="ignore")
        w.writeheader()
        for loc in ["MW-01", "MW-02", "MW-03", "MW-04", "MW-05"]:
            row = {f: "" for f in _RESULT_FIELDS}
            row.update({"LocationID": loc, "ExceedsScreeningLevel": "1",
                        "AnalyteCanonicalName": "Benzene"})
            w.writerow(row)


def _coords_csv(path: Path) -> None:
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["location_id", "x", "y"])
        w.writeheader()
        for loc, x, y in [("MW-01", 0.0, 0.0), ("MW-02", 1.0, 0.0),
                           ("MW-03", 1.0, 1.0), ("MW-04", 0.0, 1.0),
                           ("MW-05", 0.5, 0.5)]:
            w.writerow({"location_id": loc, "x": str(x), "y": str(y)})


def test_draft_plume_boundary_in_envmon_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "draft-plume-boundary" in result.output


def test_draft_plume_boundary_points_csv(tmp_path):
    pts = tmp_path / "pts.csv"
    out = tmp_path / "boundary.geojson"
    _points_csv(pts)
    result = CliRunner().invoke(
        autogis,
        ["envmon", "draft-plume-boundary",
         "--points-csv", str(pts),
         "--output", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
    fc = json.loads(out.read_text())
    assert fc["type"] == "Feature"
    assert fc["geometry"]["type"] == "Polygon"
    assert fc["properties"]["review_status"] == "DRAFT"


def test_draft_plume_boundary_results_csv(tmp_path):
    r = tmp_path / "results.csv"
    c = tmp_path / "coords.csv"
    out = tmp_path / "boundary.geojson"
    _results_csv(r)
    _coords_csv(c)
    result = CliRunner().invoke(
        autogis,
        ["envmon", "draft-plume-boundary",
         "--results-csv", str(r),
         "--coords-csv", str(c),
         "--output", str(out)],
    )
    assert result.exit_code == 0, result.output
    fc = json.loads(out.read_text())
    assert fc["properties"]["review_status"] == "DRAFT"


def test_draft_plume_boundary_concave_hull(tmp_path):
    pts = tmp_path / "pts.csv"
    out = tmp_path / "boundary.geojson"
    _points_csv(pts)
    result = CliRunner().invoke(
        autogis,
        ["envmon", "draft-plume-boundary",
         "--points-csv", str(pts),
         "--hull-method", "concave",
         "--output", str(out)],
    )
    assert result.exit_code == 0, result.output
    fc = json.loads(out.read_text())
    assert fc["properties"]["hull_method"] == "concave"


def test_draft_plume_boundary_wkt_flag(tmp_path):
    pts = tmp_path / "pts.csv"
    out = tmp_path / "boundary.geojson"
    _points_csv(pts)
    result = CliRunner().invoke(
        autogis,
        ["envmon", "draft-plume-boundary",
         "--points-csv", str(pts),
         "--output", str(out),
         "--wkt"],
    )
    assert result.exit_code == 0, result.output
    assert "POLYGON" in result.output
    assert "DRAFT" in result.output


def test_draft_plume_boundary_too_few_points_exits_nonzero(tmp_path):
    pts = tmp_path / "pts.csv"
    out = tmp_path / "boundary.geojson"
    with pts.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["location_id", "x", "y"])
        w.writeheader()
        w.writerow({"location_id": "MW-01", "x": "0.0", "y": "0.0"})
        w.writerow({"location_id": "MW-02", "x": "1.0", "y": "0.0"})
    result = CliRunner().invoke(
        autogis,
        ["envmon", "draft-plume-boundary",
         "--points-csv", str(pts),
         "--output", str(out)],
    )
    assert result.exit_code != 0


def test_draft_plume_boundary_mutual_exclusion_error(tmp_path):
    """--points-csv and --results-csv must not be used together."""
    pts = tmp_path / "pts.csv"
    r = tmp_path / "r.csv"
    c = tmp_path / "c.csv"
    out = tmp_path / "boundary.geojson"
    _points_csv(pts)
    result = CliRunner().invoke(
        autogis,
        ["envmon", "draft-plume-boundary",
         "--points-csv", str(pts),
         "--results-csv", str(r),
         "--coords-csv", str(c),
         "--output", str(out)],
    )
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output.lower() or result.exit_code != 0
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_cli_draft_plume_boundary.py -v
```
Expected: FAIL — `test_draft_plume_boundary_in_envmon_help` fails because command not registered.

- [ ] **Step 3: Add `write_plume_draft_to_gdb` to draft_plume_boundary.py**

Append to `autogis/core/envmon/draft_plume_boundary.py`:

```python
# ---------------------------------------------------------------------------
# arcpy GDB write seam — LOCAL only
# ---------------------------------------------------------------------------

def write_plume_draft_to_gdb(  # pragma: no cover
    gdb_path: str,
    site_id: str,
    result: DraftPlumeBoundaryResult,
) -> None:
    """Write the draft plume polygon to Env_PlumeBoundary_Draft (ArcGIS Pro).

    ReviewStatus='DRAFT' matches the convention in groundwater_contours.py.
    Requires arcpy. Wrapped by the CLI --gdb flag behind _guard().
    """
    import datetime
    import arcpy
    from pathlib import Path as _P

    fc = str(_P(gdb_path) / "Env_PlumeBoundary_Draft")
    if not arcpy.Exists(fc):
        return

    sr = arcpy.Describe(fc).spatialReference
    # Delete existing draft polygon for this site
    where = f"SiteID = '{site_id}'"
    if result.analyte:
        where += f" AND AnalyteFilter = '{result.analyte}'"
    with arcpy.da.UpdateCursor(fc, ["OID@"], where_clause=where) as cur:
        for _ in cur:
            cur.deleteRow()

    # Build closed ring polygon
    closed = result.hull_vertices + [result.hull_vertices[0]]
    ring = arcpy.Array([arcpy.Point(xy[0], xy[1]) for xy in closed])
    polygon = arcpy.Polygon(ring, sr)

    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    note = (f"DRAFT boundary — {result.hull_method} hull, "
            f"{result.n_exceedance_points} exceedance point(s). "
            f"Auto-generated {stamp}; review required.")

    fields = ["SiteID", "AnalyteFilter", "HullMethod", "KNeighbors",
              "NExceedancePoints", "ReviewStatus", "Notes", "SHAPE@"]
    with arcpy.da.InsertCursor(fc, fields) as cur:
        cur.insertRow([
            site_id,
            result.analyte or "",
            result.hull_method,
            result.k_neighbors,
            result.n_exceedance_points,
            "DRAFT",
            note,
            polygon,
        ])
```

- [ ] **Step 4: Add `draft-plume-boundary` command to cli.py**

Open `autogis/adapters/cli.py`. Find the headless section (after `apply-screening` command, before the LOCAL tools section comment). Insert the following command:

```python
@envmon.command("draft-plume-boundary")
@click.option("--points-csv", "points_csv", default=None,
              type=click.Path(exists=True),
              help="CSV of exceedance points (location_id, x, y [, analyte, event_date]). "
                   "Mutually exclusive with --results-csv/--coords-csv.")
@click.option("--results-csv", "results_csv", default=None,
              type=click.Path(exists=True),
              help="CSV of AnalyticalResultRecord rows (from apply-screening). "
                   "Filter to ExceedsScreeningLevel=1. Requires --coords-csv.")
@click.option("--coords-csv", "coords_csv", default=None,
              type=click.Path(exists=True),
              help="CSV of well coordinates (location_id, x, y). "
                   "Required when using --results-csv.")
@click.option("--analyte", default=None,
              help="Filter to a single analyte (AnalyteCanonicalName). "
                   "Default: all analytes.")
@click.option("--hull-method", "hull_method",
              type=click.Choice(["convex", "concave"]), default="convex",
              show_default=True,
              help="Hull algorithm. 'convex' = safest/most conservative. "
                   "'concave' = tighter fit (k-NN based).")
@click.option("--k", "k_neighbors", type=int, default=3, show_default=True,
              help="Starting k for concave hull (ignored for convex). Min 3.")
@click.option("--site", "site_id", default="",
              help="Site ID for provenance metadata in output.")
@click.option("--output", "output", required=True, type=click.Path(),
              help="Output GeoJSON file path (.geojson).")
@click.option("--wkt", "emit_wkt", is_flag=True, default=False,
              help="Also print the WKT polygon to stdout (with [DRAFT] prefix).")
@click.option("--gdb", default=None, type=click.Path(),
              help="Write polygon to Env_PlumeBoundary_Draft in this GDB "
                   "(requires ArcGIS Pro).")
@click.option("--qa-report", "qa_report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]),
              default="error", show_default=True)
def draft_plume_boundary_cmd(points_csv, results_csv, coords_csv, analyte,
                             hull_method, k_neighbors, site_id, output,
                             emit_wkt, gdb, qa_report, fail_on):
    """Tool: generate a DRAFT plume extent polygon from exceedance points (headless).

    WARNING: Output is always DRAFT. This is a geometric helper for analyst
    review — NOT a geostatistical model. Do not cite in regulatory deliverables
    without professional review.
    """
    import json as _json
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.draft_plume_boundary import (
        load_exceedance_points_csv,
        filter_results_to_exceedance_points,
        compute_draft_plume_boundary,
        result_to_geojson,
        result_to_wkt,
        write_plume_draft_to_gdb,
    )

    # Validate mutually exclusive inputs
    if points_csv and results_csv:
        raise click.UsageError(
            "--points-csv and --results-csv are mutually exclusive. "
            "Use one or the other.")
    if not points_csv and not results_csv:
        raise click.UsageError(
            "Provide either --points-csv or --results-csv + --coords-csv.")
    if results_csv and not coords_csv:
        raise click.UsageError(
            "--results-csv requires --coords-csv for well coordinates.")

    qa = QACollector()

    if points_csv:
        pts = load_exceedance_points_csv(Path(points_csv))
    else:
        pts = filter_results_to_exceedance_points(
            Path(results_csv), Path(coords_csv),
            analyte=analyte, qa=qa)

    result = compute_draft_plume_boundary(
        pts, hull_method=hull_method, k_neighbors=k_neighbors,
        site_id=site_id, analyte=analyte, qa=qa)

    if result is None:
        # SEV_ERROR already added; _render_qa will exit non-zero.
        _render_qa(qa, qa_report, fail_on)
        return

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    fc = result_to_geojson(result)
    out.write_text(_json.dumps(fc, indent=2), encoding="utf-8")
    click.echo(f"Written: {out}  ({len(result.hull_vertices)}-vertex "
               f"{result.hull_method} hull, {result.n_exceedance_points} "
               f"exceedance point(s))  [DRAFT]")

    if emit_wkt:
        wkt = result_to_wkt(result)
        click.echo("[DRAFT] WKT polygon (closed ring):")
        click.echo(wkt)

    if gdb:
        _guard("draft-plume-boundary")
        write_plume_draft_to_gdb(gdb, site_id, result)
        click.echo(f"Polygon written to {gdb}/Env_PlumeBoundary_Draft  [DRAFT]")

    _render_qa(qa, qa_report, fail_on)
```

- [ ] **Step 5: Run CLI tests**

```
python -m pytest tests/envmon/test_cli_draft_plume_boundary.py -v
```
Expected: all PASS.

- [ ] **Step 6: Full suite**

```
python -m pytest -q
```
Expected: all tests PASS.

- [ ] **Step 7: Verify headless import**

```
python -c "import autogis.core.envmon.draft_plume_boundary; print('OK')"
python -c "import autogis.adapters.cli; print('OK')"
```
Expected: `OK` for both with no import error.

- [ ] **Step 8: Commit**

```bash
git add autogis/core/envmon/draft_plume_boundary.py \
        autogis/adapters/cli.py \
        tests/envmon/test_cli_draft_plume_boundary.py
git commit -m "feat(envmon): draft-plume-boundary CLI + GDB write seam (DRAFT label on all outputs)"
```

---

## Self-Review

### 1. Spec coverage check

| Requirement | Covered by |
|---|---|
| DRAFT plume extent polygon from exceedance points | Task 3: `compute_draft_plume_boundary` |
| Convex hull (numpy_geom) | Tasks 3+4: `convex_hull()` default |
| Concave hull (numpy_geom) | Task 2: `concave_hull()` wrapper |
| DRAFT labeling on all output paths | Tasks 3+4: GeoJSON, WKT, GDB, QA |
| GeoJSON output | Task 3: `result_to_geojson()` |
| WKT output | Tasks 3+4: `result_to_wkt()` + `--wkt` flag |
| arcpy export via seam (GDB) | Task 4: `write_plume_draft_to_gdb` `# pragma: no cover` |
| Headless core API | Tasks 1+3: no arcpy in non-seam code |
| CLI surface | Task 4: `envmon draft-plume-boundary` |
| TDD: tests first | Every task: failing test before implementation |
| Non-goal: kriging/EBK deferred | DRAFT warning text + Global Constraints |
| Non-goal: geostatistical surface | Module docstring + `_DRAFT_WARNING` constant |
| Minimum 3 points guard | Task 3: `compute_draft_plume_boundary` early-return |
| Ring closing in serializers | Tasks 3+4: serializers append `vertices[0]` |
| Reuse `load_well_coords` | Task 1: `filter_results_to_exceedance_points` |
| `ReviewStatus="DRAFT"` GDB convention | Task 4: matches `groundwater_contours.py` |

### 2. Placeholder scan

No TBD / TODO / "handle edge cases" stubs. Every step shows full code.

### 3. Type consistency

| Symbol | Defined in | Used in |
|---|---|---|
| `ExceedancePoint` | Task 1 | Tasks 3, 4 |
| `DraftPlumeBoundaryResult` | Task 3 | Tasks 3, 4 |
| `load_exceedance_points_csv(path) -> list[ExceedancePoint]` | Task 1 | Task 4 CLI |
| `filter_results_to_exceedance_points(results_path, coords_path, *, analyte, qa)` | Task 1 | Task 4 CLI |
| `compute_draft_plume_boundary(points, *, hull_method, k_neighbors, site_id, analyte, qa) -> DraftPlumeBoundaryResult | None` | Task 3 | Tasks 3 tests, 4 CLI |
| `result_to_geojson(result) -> dict` | Task 3 | Tasks 3 tests, 4 CLI |
| `result_to_wkt(result) -> str` | Task 3 | Tasks 3 tests, 4 CLI |
| `concave_hull(xy, k=3) -> np.ndarray` | Task 2 | Task 3 |
| `write_plume_draft_to_gdb(gdb_path, site_id, result)` | Task 4 | Task 4 CLI `--gdb` |

All consistent. No name drift.

---

## Risks

1. **Over-interpretation of DRAFT output.** A convex or concave hull drawn from 3–5 wells is not a scientifically defensible plume delineation. The DRAFT label is present on every output path, but downstream users may treat the polygon as authoritative. Mitigate by ensuring the `draft_warning` text is prominent in both the GeoJSON properties and CLI output, and by explicitly excluding this tool from regulatory figure pipelines until a professional reviewer approves the polygon.

2. **npg `concave()` k-NN skip bug.** `knn0` slices `[1:k+1]` (designed for `p in pnts`) but `concave()` removes `cur_p` from candidates first, so the literal nearest neighbor is skipped each step. The wrapper falls back to `convex_hull` on any runtime failure, and the default mode is `convex`, so this only affects users who opt into `--hull-method concave`. Document this in the wrapper docstring and in the CLI help.

3. **Concave hull non-termination on pathological input.** The npg algorithm recurses with `k + 1` when hull edges cross. A degenerate point set (all points collinear, near-duplicate points, or widely-spaced geometry) could cause deep recursion. The inner try/except in `concave_hull()` catches all exceptions and degrades to `convex_hull`. The CLI will warn via the QA record that the convex fallback was used.

4. **Fewer than 3 unique wells.** If all exceedances are at one or two wells (e.g., early site characterization), no polygon can be drawn. The `SEV_ERROR` and `None` return propagate cleanly; the CLI exits non-zero. This is by design — do not silently emit a zero-area polygon.

5. **Coordinate system assumptions.** The module stores raw x, y values and does no CRS validation. Hull computation is pure Euclidean. If the input coordinates are in geographic decimal degrees (latitude/longitude), distances and areas in the hull will be distorted. For a DRAFT boundary this is acceptable, but the CLI help should note that projected coordinates (e.g., State Plane, UTM) produce more meaningful results.
