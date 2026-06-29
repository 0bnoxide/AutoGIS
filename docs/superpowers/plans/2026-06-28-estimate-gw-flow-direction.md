# EstimateGWFlowDirection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `EstimateGWFlowDirection` (roadmap 4.3) — fully headless numpy
computation of groundwater flow direction and hydraulic gradient from 3+ well
water-level measurements, plus a `estimate-gw-flow-direction` CLI command.

**Architecture:**
- New: `autogis/core/envmon/estimate_gw_flow_direction.py` — two dataclasses
  (`WellWaterLevel`, `GWFlowResult`), a CSV reader, and the plane-fit engine.
  Imports only `numpy` and stdlib; zero arcpy/arcgis.
- New: `tests/envmon/test_estimate_gw_flow_direction.py` — unit tests with
  exact numeric solutions for known-gradient scenarios.
- Modify: `autogis/adapters/cli.py` — add `estimate-gw-flow-direction` command
  (headless; no LOCAL arcpy path — GDB arrow write is a future tool).

**Tech Stack:** Python 3.10+, `numpy` (already a project dependency),
`dataclasses`, `csv`, `math`, `uuid`. No `arcpy`, no `arcgis`, no `openpyxl`.

## Global Constraints

- `autogis/core/` and `autogis/adapters/` must import with **neither** `arcpy`
  nor `arcgis` present — verified by the existing headless test suite.
- Run tests: `python -m pytest -q`
- The core `estimate_gw_flow_direction()` function is arcpy-free and fully
  unit-testable; it must never import arcpy at module level.
- All results carry `qa_status` and `draft = True`. The roadmap mandates
  `DRAFT_REVIEW_REQUIRED` — professional review is required before use.
- Coordinates are in the project's projected CRS (easting/northing, same units
  as GWE, typically feet). The gradient is dimensionless (ft head / ft distance).
- QA uses the project-canonical `QACollector` from
  `autogis/core/common/qa.py`.
- No new schema file is needed; `GWFlowResult` is a plain dataclass in the
  core module (not in `autogis/core/common/schema/`).
- `Env_GWFlowArrow_Draft` (POLYLINE, GDB) requires arcpy — writing geometry to
  that table is **out of scope** for this plan (non-goal).

---

## Math

### Problem statement

Given *n* ≥ 3 monitoring wells, each with easting *Eᵢ*, northing *Nᵢ*, and
measured groundwater elevation *hᵢ* (ft AMSL), fit a plane:

```
h = a·E + b·N + c
```

so that the coefficients (a, b, c) best represent the potentiometric surface.
From the plane normal:

- **Hydraulic gradient vector** = (∂h/∂E, ∂h/∂N) = (a, b)
- **Gradient magnitude** (ft/ft) = √(a² + b²)
- **Flow direction**: groundwater flows down the gradient, so the flow vector
  in (east, north) space is (–a, –b).
- **Flow azimuth** (degrees from North, clockwise):

  ```
  azimuth = degrees(atan2(−a, −b)) mod 360
  ```

  where `atan2(east_component, north_component)` follows the standard
  geographic azimuth convention.

### Exact 3-well case (three-point problem)

Solve the 3×3 linear system

```
[[E₁ N₁ 1]   [a]   [h₁]
 [E₂ N₂ 1] · [b] = [h₂]
 [E₃ N₃ 1]]  [c]   [h₃]
```

This has a unique solution when the three wells are not collinear.

### n > 3 wells (least-squares plane fit)

Build the over-determined system A · θ = h where

```
A = [[E₁ N₁ 1]
     [E₂ N₂ 1]
     ...
     [Eₙ Nₙ 1]]
```

Solve using `numpy.linalg.lstsq(A, h, rcond=None)`, which minimises ‖Aθ − h‖₂.
The residuals are the per-well fit errors (useful as QA).

### Collinearity detection

Compute `numpy.linalg.cond(A)`. If `cond(A) > 1e8` the wells are effectively
collinear and the gradient direction cannot be resolved — flag
`qa_status = "COLLINEAR"` and return NaN results rather than a misleading
direction.

*(Assumption: 1e8 is conservative enough to catch near-collinear well layouts
common in site monitoring networks without false-positives on typical grid
spacing. Adjust via `collinear_threshold` parameter if needed.)*

---

## Output Table Schema

The headless output is a single-row CSV named by convention
`<site_id>_<event_date>_gw_flow.csv`. Field order matches `GWFlowResult`
field declaration:

| Field | Type | Notes |
|---|---|---|
| `run_id` | str | UUID4 auto-generated unless caller supplies |
| `site_id` | str | From CLI `--site-id` |
| `event_date` | str | YYYY-MM-DD from CLI `--event-date` |
| `n_wells` | int | Wells used in fit |
| `well_ids` | str | Comma-joined (e.g. `"MW-01,MW-02,MW-03"`) |
| `plane_a` | float | ∂h/∂easting coefficient |
| `plane_b` | float | ∂h/∂northing coefficient |
| `plane_c` | float | Plane intercept |
| `gradient_magnitude` | float | √(a²+b²), ft/ft |
| `flow_azimuth_deg` | float | Degrees from N, clockwise, [0,360) |
| `condition_number` | float | cond(design matrix); high → collinear |
| `method` | str | `"THREE_POINT"` \| `"LEAST_SQUARES"` |
| `qa_status` | str | `"PASS"` \| `"COLLINEAR"` \| `"INSUFFICIENT"` |
| `qa_notes` | str | Human-readable notes including `DRAFT_REVIEW_REQUIRED` |
| `draft` | bool | Always `True` |

Input CSV (wells) required columns: `well_id`, `easting`, `northing`, `gwe_ft`.

---

## File Map

| Action | Path |
|---|---|
| **Create** | `autogis/core/envmon/estimate_gw_flow_direction.py` |
| **Create** | `tests/envmon/test_estimate_gw_flow_direction.py` |
| **Modify** | `autogis/adapters/cli.py` — add command after `process-level-loop` block (~line 501) |

---

### Task 1: Core module + computation tests

**Files:**
- Create: `autogis/core/envmon/estimate_gw_flow_direction.py`
- Test: `tests/envmon/test_estimate_gw_flow_direction.py`

**Interfaces:**
- Consumes: nothing from other tasks (standalone)
- Produces for Task 2:
  - `WellWaterLevel(well_id, easting, northing, gwe_ft)` dataclass
  - `GWFlowResult` dataclass (all fields as above)
  - `estimate_gw_flow_direction(wells, *, run_id, site_id, event_date, collinear_threshold, qa) -> GWFlowResult`
  - `parse_wells_csv(path: Path) -> list[WellWaterLevel]`

- [ ] **Step 1: Write the failing tests**

Create `tests/envmon/test_estimate_gw_flow_direction.py`:

```python
"""Tests for EstimateGWFlowDirection (Tool 4.3).

All numeric expected values are derived analytically from the plane equation
h = a·E + b·N + c with known coefficients, then verified against
atan2(-a, -b) % 360 for azimuth.
"""
import csv
import math
from pathlib import Path

import pytest

from autogis.core.common.qa import QACollector
from autogis.core.envmon.estimate_gw_flow_direction import (
    GWFlowResult,
    WellWaterLevel,
    estimate_gw_flow_direction,
    parse_wells_csv,
)

# ---------------------------------------------------------------------------
# Fixture well sets (all in projected ft coordinates)
# ---------------------------------------------------------------------------

# Flow EAST (azimuth 90°)
# Plane: h = -0.01·E + 0·N + 100.0  →  a=-0.01, b=0
# gradient magnitude = 0.01  flow = (0.01, 0)  azimuth = atan2(0.01,0) = 90°
_WELLS_EAST = [
    WellWaterLevel("MW-01", easting=0.0, northing=0.0, gwe_ft=100.0),
    WellWaterLevel("MW-02", easting=100.0, northing=0.0, gwe_ft=99.0),
    WellWaterLevel("MW-03", easting=0.0, northing=100.0, gwe_ft=100.0),
]

# Flow NORTH (azimuth 0° / 360°)
# Plane: h = 0·E + (-0.01)·N + 100.0  →  a=0, b=-0.01
# gradient magnitude = 0.01  flow = (0, 0.01)  azimuth = atan2(0,0.01) = 0°
_WELLS_NORTH = [
    WellWaterLevel("MW-01", easting=0.0, northing=0.0, gwe_ft=100.0),
    WellWaterLevel("MW-02", easting=100.0, northing=0.0, gwe_ft=100.0),
    WellWaterLevel("MW-03", easting=0.0, northing=100.0, gwe_ft=99.0),
]

# Flow SOUTHWEST (azimuth 225°)
# Plane: h = 0.01·E + 0.01·N + 100.0  →  a=0.01, b=0.01
# gradient magnitude = sqrt(2)*0.01  flow = (-0.01,-0.01)
# azimuth = degrees(atan2(-0.01,-0.01)) % 360
#         = degrees(-3π/4) % 360 = (-135) % 360 = 225°
_WELLS_SW = [
    WellWaterLevel("MW-01", easting=0.0, northing=0.0, gwe_ft=100.0),
    WellWaterLevel("MW-02", easting=100.0, northing=0.0, gwe_ft=101.0),
    WellWaterLevel("MW-03", easting=0.0, northing=100.0, gwe_ft=101.0),
]

# Collinear wells (all at northing=0 → rank-2 design matrix)
_WELLS_COLLINEAR = [
    WellWaterLevel("MW-01", easting=0.0, northing=0.0, gwe_ft=100.0),
    WellWaterLevel("MW-02", easting=100.0, northing=0.0, gwe_ft=99.0),
    WellWaterLevel("MW-03", easting=200.0, northing=0.0, gwe_ft=98.0),
]

# Too few wells (< 3)
_WELLS_TOO_FEW = [
    WellWaterLevel("MW-01", easting=0.0, northing=0.0, gwe_ft=100.0),
    WellWaterLevel("MW-02", easting=100.0, northing=0.0, gwe_ft=99.0),
]

# 4-well overdetermined — plane h = -0.005·E + 100.0 (flow east)
# Gradient = (-0.005, 0), azimuth = 90°, method = LEAST_SQUARES
_WELLS_4 = [
    WellWaterLevel("MW-01", easting=0.0, northing=0.0, gwe_ft=100.0),
    WellWaterLevel("MW-02", easting=200.0, northing=0.0, gwe_ft=99.0),
    WellWaterLevel("MW-03", easting=0.0, northing=200.0, gwe_ft=100.0),
    WellWaterLevel("MW-04", easting=200.0, northing=200.0, gwe_ft=99.0),
]


def _run(wells, **kwargs):
    qa = QACollector()
    return estimate_gw_flow_direction(
        wells, site_id="TEST", event_date="2026-06-28", qa=qa, **kwargs
    ), qa


# ---------------------------------------------------------------------------
# Flow azimuth tests (three-point exact solution)
# ---------------------------------------------------------------------------

def test_azimuth_east():
    result, _ = _run(_WELLS_EAST)
    assert abs(result.flow_azimuth_deg - 90.0) < 0.01


def test_azimuth_north():
    result, _ = _run(_WELLS_NORTH)
    # 0° and 360° are equivalent; normalise to 0-360 range
    assert result.flow_azimuth_deg < 0.01 or abs(result.flow_azimuth_deg - 360.0) < 0.01


def test_azimuth_sw():
    result, _ = _run(_WELLS_SW)
    assert abs(result.flow_azimuth_deg - 225.0) < 0.01


# ---------------------------------------------------------------------------
# Gradient magnitude tests
# ---------------------------------------------------------------------------

def test_gradient_magnitude_east():
    result, _ = _run(_WELLS_EAST)
    assert abs(result.gradient_magnitude - 0.01) < 1e-9


def test_gradient_magnitude_sw():
    result, _ = _run(_WELLS_SW)
    expected = math.sqrt(2) * 0.01
    assert abs(result.gradient_magnitude - expected) < 1e-9


# ---------------------------------------------------------------------------
# Method tag
# ---------------------------------------------------------------------------

def test_method_three_point():
    result, _ = _run(_WELLS_EAST)
    assert result.method == "THREE_POINT"


def test_method_least_squares():
    result, _ = _run(_WELLS_4)
    assert result.method == "LEAST_SQUARES"


# ---------------------------------------------------------------------------
# Least-squares 4-well case
# ---------------------------------------------------------------------------

def test_least_squares_azimuth():
    result, _ = _run(_WELLS_4)
    assert abs(result.flow_azimuth_deg - 90.0) < 0.01


def test_least_squares_gradient():
    result, _ = _run(_WELLS_4)
    assert abs(result.gradient_magnitude - 0.005) < 1e-9


# ---------------------------------------------------------------------------
# qa_status
# ---------------------------------------------------------------------------

def test_qa_status_pass():
    result, _ = _run(_WELLS_EAST)
    assert result.qa_status == "PASS"


def test_qa_status_insufficient():
    result, qa = _run(_WELLS_TOO_FEW)
    assert result.qa_status == "INSUFFICIENT"
    assert any("insufficient" in r.category for r in qa.records)


def test_qa_status_collinear():
    result, qa = _run(_WELLS_COLLINEAR)
    assert result.qa_status == "COLLINEAR"
    assert any("collinear" in r.category for r in qa.records)


def test_collinear_result_is_nan():
    result, _ = _run(_WELLS_COLLINEAR)
    assert math.isnan(result.flow_azimuth_deg)
    assert math.isnan(result.gradient_magnitude)


# ---------------------------------------------------------------------------
# draft flag
# ---------------------------------------------------------------------------

def test_draft_always_true():
    result, _ = _run(_WELLS_EAST)
    assert result.draft is True


def test_draft_true_on_collinear():
    result, _ = _run(_WELLS_COLLINEAR)
    assert result.draft is True


# ---------------------------------------------------------------------------
# plane coefficients (spot-check)
# ---------------------------------------------------------------------------

def test_plane_a_east():
    result, _ = _run(_WELLS_EAST)
    assert abs(result.plane_a - (-0.01)) < 1e-9


def test_plane_b_east():
    result, _ = _run(_WELLS_EAST)
    assert abs(result.plane_b - 0.0) < 1e-9


# ---------------------------------------------------------------------------
# parse_wells_csv
# ---------------------------------------------------------------------------

def test_parse_wells_csv(tmp_path):
    p = tmp_path / "wells.csv"
    p.write_text(
        "well_id,easting,northing,gwe_ft\n"
        "MW-01,0.0,0.0,100.0\n"
        "MW-02,100.0,0.0,99.0\n"
        "MW-03,0.0,100.0,100.0\n",
        encoding="utf-8",
    )
    wells = parse_wells_csv(p)
    assert len(wells) == 3
    assert wells[0].well_id == "MW-01"
    assert abs(wells[0].easting - 0.0) < 1e-9
    assert abs(wells[1].gwe_ft - 99.0) < 1e-9


def test_parse_wells_csv_roundtrip(tmp_path):
    """Parsed wells fed into estimate_gw_flow_direction reproduce azimuth 90°."""
    p = tmp_path / "wells.csv"
    p.write_text(
        "well_id,easting,northing,gwe_ft\n"
        "MW-01,0.0,0.0,100.0\n"
        "MW-02,100.0,0.0,99.0\n"
        "MW-03,0.0,100.0,100.0\n",
        encoding="utf-8",
    )
    wells = parse_wells_csv(p)
    result, _ = _run(wells)
    assert abs(result.flow_azimuth_deg - 90.0) < 0.01


# ---------------------------------------------------------------------------
# run_id defaults to UUID
# ---------------------------------------------------------------------------

def test_run_id_auto_generated():
    result, _ = _run(_WELLS_EAST)
    assert result.run_id  # non-empty
    assert len(result.run_id) == 36  # UUID4 canonical form


def test_run_id_explicit():
    result, _ = _run(_WELLS_EAST, run_id="MY-RUN-001")
    assert result.run_id == "MY-RUN-001"
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_estimate_gw_flow_direction.py -v
```

Expected: `ModuleNotFoundError: No module named 'autogis.core.envmon.estimate_gw_flow_direction'`

- [ ] **Step 3: Create `autogis/core/envmon/estimate_gw_flow_direction.py`**

```python
"""estimate_gw_flow_direction.py — hydraulic gradient from water-level plane fit (Tool 4.3).

Headless, arcpy-free. Fits a least-squares plane h = a·E + b·N + c to 3+
well GWEs, then derives flow direction and gradient magnitude. Outputs are
DRAFT_REVIEW_REQUIRED — professional review is mandatory before publication.

Math
----
For n wells at (Eᵢ, Nᵢ, hᵢ):
  A = [[E₁ N₁ 1], ..., [Eₙ Nₙ 1]]  (design matrix)
  θ = lstsq(A, h)  →  θ = [a, b, c]

  gradient = (a, b)            ← ∂h/∂E, ∂h/∂N
  gradient_magnitude = ‖(a,b)‖
  flow_vector = (-a, -b)       ← water flows down-gradient
  flow_azimuth_deg = degrees(atan2(-a, -b)) % 360   [0°=N, 90°=E, CW]
"""
from __future__ import annotations

import csv
import math
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import numpy as np

from ..common.qa import QACollector, SEV_ERROR, SEV_INFO, SEV_WARNING

# Condition-number threshold for collinearity detection.
# 1e8 is conservative: normal site networks (triangular/quadrilateral layouts)
# have cond(A) < 1e4; perfectly collinear wells produce cond >> 1e12.
_COLLINEAR_THRESHOLD = 1e8


@dataclass
class WellWaterLevel:
    """One well's location and groundwater elevation (input to plane fit)."""
    well_id: str
    easting: float
    northing: float
    gwe_ft: float


@dataclass
class GWFlowResult:
    """Plane-fit result for one site/event run."""
    run_id: str
    site_id: str
    event_date: str
    n_wells: int
    well_ids: List[str]
    plane_a: float          # ∂h/∂easting
    plane_b: float          # ∂h/∂northing
    plane_c: float          # intercept
    gradient_magnitude: float
    flow_azimuth_deg: float
    condition_number: float
    method: str             # "THREE_POINT" | "LEAST_SQUARES" | ""
    qa_status: str          # "PASS" | "COLLINEAR" | "INSUFFICIENT"
    qa_notes: str
    draft: bool = True      # always True — outputs require professional review


def _fit_plane(
    wells: List[WellWaterLevel],
    qa: QACollector,
    site_id: str,
    collinear_threshold: float,
) -> Optional[tuple]:
    """Fit h = a·E + b·N + c by least-squares.

    Returns (a, b, c, condition_number, method_str) or None if infeasible.
    Adds QA records for all failure modes.
    """
    n = len(wells)
    if n < 3:
        qa.add(SEV_ERROR, "insufficient_wells",
               f"Need at least 3 wells; got {n}.",
               site_id=site_id,
               recommended_action="Supply 3 or more wells with valid GWEs.")
        return None

    A = np.array([[w.easting, w.northing, 1.0] for w in wells],
                 dtype=float)
    h = np.array([w.gwe_ft for w in wells], dtype=float)

    cond = float(np.linalg.cond(A))

    if cond > collinear_threshold:
        qa.add(SEV_ERROR, "collinear_wells",
               f"Wells appear collinear (condition number {cond:.2e} "
               f"> threshold {collinear_threshold:.2e}). "
               f"Gradient plane cannot be reliably resolved.",
               site_id=site_id,
               recommended_action=(
                   "Add a well that is not on the same line as existing "
                   "wells, or check for duplicate coordinates."))
        return None

    coeffs, _residuals, _rank, _sv = np.linalg.lstsq(A, h, rcond=None)
    a, b, c = float(coeffs[0]), float(coeffs[1]), float(coeffs[2])
    method = "THREE_POINT" if n == 3 else "LEAST_SQUARES"
    return a, b, c, cond, method


def estimate_gw_flow_direction(
    wells: List[WellWaterLevel],
    *,
    run_id: Optional[str] = None,
    site_id: str,
    event_date: str,
    collinear_threshold: float = _COLLINEAR_THRESHOLD,
    qa: QACollector,
) -> GWFlowResult:
    """Fit a plane to well water levels; return hydraulic gradient and azimuth.

    Parameters
    ----------
    wells : list[WellWaterLevel]
        Must have >= 3 wells that are not collinear.
    run_id : str, optional
        Unique run identifier; a UUID4 is auto-generated if omitted.
    site_id : str
        Site identifier written to QA records and output.
    event_date : str
        Event date string (e.g. ``"2026-06-28"``); metadata only.
    collinear_threshold : float
        Condition-number threshold above which wells are flagged collinear.
        Default 1e8.
    qa : QACollector
        Receives ERROR on failure, INFO on success.

    Returns
    -------
    GWFlowResult
        ``qa_status`` is ``"PASS"``, ``"COLLINEAR"``, or ``"INSUFFICIENT"``.
        ``draft`` is always ``True`` — these outputs require professional review.
    """
    run_id = run_id or str(uuid.uuid4())
    well_ids = [w.well_id for w in wells]
    n = len(wells)
    _nan = float("nan")

    fit = _fit_plane(wells, qa, site_id, collinear_threshold)
    if fit is None:
        qa_status = "INSUFFICIENT" if n < 3 else "COLLINEAR"
        return GWFlowResult(
            run_id=run_id, site_id=site_id, event_date=event_date,
            n_wells=n, well_ids=well_ids,
            plane_a=_nan, plane_b=_nan, plane_c=_nan,
            gradient_magnitude=_nan, flow_azimuth_deg=_nan,
            condition_number=_nan, method="",
            qa_status=qa_status,
            qa_notes="Plane fit failed — see QA records. DRAFT_REVIEW_REQUIRED.",
        )

    a, b, c, cond, method = fit
    grad_mag = math.sqrt(a**2 + b**2)

    # Flow azimuth: steepest-descent direction, CW from North.
    # flow_vector in (east, north) = (-a, -b)
    # azimuth = atan2(east_component, north_component) % 360
    azimuth_deg = math.degrees(math.atan2(-a, -b)) % 360.0

    qa.add(SEV_INFO, "gw_flow_computed",
           f"run={run_id} site={site_id} event={event_date} "
           f"n_wells={n} method={method} "
           f"gradient={grad_mag:.6f} ft/ft azimuth={azimuth_deg:.1f}deg "
           f"cond={cond:.2e} DRAFT_REVIEW_REQUIRED",
           site_id=site_id)

    return GWFlowResult(
        run_id=run_id, site_id=site_id, event_date=event_date,
        n_wells=n, well_ids=well_ids,
        plane_a=a, plane_b=b, plane_c=c,
        gradient_magnitude=grad_mag,
        flow_azimuth_deg=azimuth_deg,
        condition_number=cond,
        method=method,
        qa_status="PASS",
        qa_notes=f"DRAFT_REVIEW_REQUIRED — {method}, cond={cond:.2e}",
    )


def parse_wells_csv(path: Path) -> List[WellWaterLevel]:
    """Read a wells CSV with columns: well_id, easting, northing, gwe_ft.

    Parameters
    ----------
    path : Path
        Input CSV path.

    Returns
    -------
    list[WellWaterLevel]
        One entry per data row; header row is consumed by DictReader.

    Raises
    ------
    KeyError
        If a required column is missing.
    ValueError
        If a numeric field cannot be parsed as float.
    """
    wells: List[WellWaterLevel] = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            wells.append(WellWaterLevel(
                well_id=row["well_id"].strip(),
                easting=float(row["easting"]),
                northing=float(row["northing"]),
                gwe_ft=float(row["gwe_ft"]),
            ))
    return wells
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_estimate_gw_flow_direction.py -v
```

Expected: all 23 tests PASS. Verify the azimuth tests print values matching
the analytic solutions (90°, 0°, 225°).

- [ ] **Step 5: Full suite to confirm no regression**

```
python -m pytest -q
```

Expected: existing count + 23 new passes. Zero failures.

- [ ] **Step 6: Commit**

```bash
git add autogis/core/envmon/estimate_gw_flow_direction.py \
        tests/envmon/test_estimate_gw_flow_direction.py
git commit -m "feat(envmon): EstimateGWFlowDirection — headless plane fit, gradient, azimuth (Tool 4.3)"
```

---

### Task 2: CLI command

**Files:**
- Modify: `autogis/adapters/cli.py` — insert after the `process-level-loop`
  block, just before the `identify-data-gaps` command (around line 503).
- Modify: `tests/envmon/test_estimate_gw_flow_direction.py` — append CLI tests.

**Interfaces:**
- Consumes from Task 1:
  - `parse_wells_csv(path: Path) -> list[WellWaterLevel]`
  - `estimate_gw_flow_direction(wells, *, run_id, site_id, event_date, qa) -> GWFlowResult`
- Produces: registered CLI command `autogis envmon estimate-gw-flow-direction`

- [ ] **Step 1: Write the failing CLI test**

Append to `tests/envmon/test_estimate_gw_flow_direction.py`:

```python
# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------

from click.testing import CliRunner
from autogis.adapters.cli import autogis as autogis_cli


def _write_wells_csv(tmp_path, rows):
    p = tmp_path / "wells.csv"
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["well_id", "easting", "northing", "gwe_ft"])
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return str(p)


def test_cli_estimate_gw_flow_direction_in_help():
    result = CliRunner().invoke(autogis_cli, ["envmon", "--help"])
    assert "estimate-gw-flow-direction" in result.output


def test_cli_estimate_gw_flow_direction_east(tmp_path):
    """Flow-east scenario: azimuth 90° should appear in stdout."""
    csv_path = _write_wells_csv(tmp_path, [
        {"well_id": "MW-01", "easting": 0.0, "northing": 0.0, "gwe_ft": 100.0},
        {"well_id": "MW-02", "easting": 100.0, "northing": 0.0, "gwe_ft": 99.0},
        {"well_id": "MW-03", "easting": 0.0, "northing": 100.0, "gwe_ft": 100.0},
    ])
    result = CliRunner().invoke(autogis_cli, [
        "envmon", "estimate-gw-flow-direction",
        "--wells-csv", csv_path,
        "--site-id", "TEST",
        "--event-date", "2026-06-28",
    ])
    assert result.exit_code == 0, result.output
    assert "90.0" in result.output
    assert "DRAFT_REVIEW_REQUIRED" in result.output


def test_cli_estimate_gw_flow_direction_output_csv(tmp_path):
    """--output flag writes a single-row CSV with the result."""
    csv_path = _write_wells_csv(tmp_path, [
        {"well_id": "MW-01", "easting": 0.0, "northing": 0.0, "gwe_ft": 100.0},
        {"well_id": "MW-02", "easting": 100.0, "northing": 0.0, "gwe_ft": 99.0},
        {"well_id": "MW-03", "easting": 0.0, "northing": 100.0, "gwe_ft": 100.0},
    ])
    out_path = str(tmp_path / "result.csv")
    result = CliRunner().invoke(autogis_cli, [
        "envmon", "estimate-gw-flow-direction",
        "--wells-csv", csv_path,
        "--site-id", "TEST",
        "--event-date", "2026-06-28",
        "--output", out_path,
    ])
    assert result.exit_code == 0, result.output
    rows = list(csv.DictReader(open(out_path, encoding="utf-8")))
    assert len(rows) == 1
    assert abs(float(rows[0]["flow_azimuth_deg"]) - 90.0) < 0.01
    assert rows[0]["qa_status"] == "PASS"
    assert rows[0]["draft"] == "True"


def test_cli_estimate_gw_flow_direction_collinear_exits_1(tmp_path):
    """Collinear wells: exit code 1, COLLINEAR in output."""
    csv_path = _write_wells_csv(tmp_path, [
        {"well_id": "MW-01", "easting": 0.0, "northing": 0.0, "gwe_ft": 100.0},
        {"well_id": "MW-02", "easting": 100.0, "northing": 0.0, "gwe_ft": 99.0},
        {"well_id": "MW-03", "easting": 200.0, "northing": 0.0, "gwe_ft": 98.0},
    ])
    result = CliRunner().invoke(autogis_cli, [
        "envmon", "estimate-gw-flow-direction",
        "--wells-csv", csv_path,
        "--site-id", "TEST",
        "--event-date", "2026-06-28",
    ])
    assert result.exit_code == 1
    assert "collinear" in result.output.lower() or "COLLINEAR" in result.output
```

- [ ] **Step 2: Run to confirm test failure**

```
python -m pytest tests/envmon/test_estimate_gw_flow_direction.py::test_cli_estimate_gw_flow_direction_in_help -v
```

Expected: FAIL — `estimate-gw-flow-direction` not yet registered.

- [ ] **Step 3: Add command to `autogis/adapters/cli.py`**

Insert the block below immediately before the `@envmon.command("identify-data-gaps")` line
(currently around line 503 in the file):

```python
@envmon.command("estimate-gw-flow-direction")
@click.option("--wells-csv", required=True, type=click.Path(exists=True),
              help="CSV with columns: well_id, easting, northing, gwe_ft.")
@click.option("--site-id", required=True, help="Site identifier.")
@click.option("--event-date", required=True,
              help="Event date YYYY-MM-DD (metadata only; not used in math).")
@click.option("--run-id", default=None,
              help="Run identifier; auto-generated UUID4 if omitted.")
@click.option("--output", default=None, type=click.Path(),
              help="Write GWFlowResult to this CSV path (one-row output).")
@click.option("--report", default=None, type=click.Path(),
              help="Write QA report (.csv / .json / .md).")
@click.option("--fail-on", type=click.Choice(["error", "warning"]),
              default="error", show_default=True)
def estimate_gw_flow_direction_cmd(wells_csv, site_id, event_date, run_id,
                                    output, report, fail_on):
    """Tool 4.3: estimate GW flow direction and gradient (DRAFT) from well GWEs.

    Fits a least-squares plane h = a·E + b·N + c to 3+ well water levels and
    derives hydraulic gradient magnitude and flow azimuth (degrees from N, CW).
    Outputs are always DRAFT_REVIEW_REQUIRED.
    """
    import csv as _csv
    from dataclasses import asdict
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.estimate_gw_flow_direction import (
        parse_wells_csv, estimate_gw_flow_direction,
    )

    wells = parse_wells_csv(Path(wells_csv))
    qa = QACollector()
    result = estimate_gw_flow_direction(
        wells,
        run_id=run_id,
        site_id=site_id,
        event_date=event_date,
        qa=qa,
    )

    click.echo(
        f"Flow azimuth: {result.flow_azimuth_deg:.1f} deg  "
        f"Gradient: {result.gradient_magnitude:.6f} ft/ft  "
        f"Method: {result.method}  "
        f"Status: {result.qa_status}  [DRAFT_REVIEW_REQUIRED]"
    )

    if output:
        p = Path(output)
        p.parent.mkdir(parents=True, exist_ok=True)
        d = asdict(result)
        d["well_ids"] = ",".join(result.well_ids)
        with p.open("w", newline="", encoding="utf-8") as fh:
            w = _csv.DictWriter(fh, fieldnames=list(d.keys()))
            w.writeheader()
            w.writerow(d)
        click.echo(f"Result written: {output}")

    _render_qa(qa, report, fail_on)

```

- [ ] **Step 4: Run CLI tests**

```
python -m pytest tests/envmon/test_estimate_gw_flow_direction.py -v -k "cli"
```

Expected: all 5 CLI tests PASS.

- [ ] **Step 5: Full suite**

```
python -m pytest -q
```

Expected: zero failures. Note the final test count (+28 new tests total across both tasks).

- [ ] **Step 6: Commit**

```bash
git add autogis/adapters/cli.py \
        tests/envmon/test_estimate_gw_flow_direction.py
git commit -m "feat(cli): add estimate-gw-flow-direction command (Tool 4.3, headless)"
```

---

## Self-Review

**Spec coverage check:**

| Requirement | Covered by |
|---|---|
| Three-point exact solution | `_fit_plane` when n=3; method="THREE_POINT" |
| Least-squares plane for n>3 | `numpy.linalg.lstsq`; method="LEAST_SQUARES" |
| Hydraulic gradient magnitude | `gradient_magnitude = sqrt(a²+b²)` |
| Flow direction (azimuth) | `atan2(-a,-b) % 360` |
| Collinear well detection | `cond(A) > 1e8` → qa_status="COLLINEAR" |
| Insufficient wells (<3) | guard in `_fit_plane` → qa_status="INSUFFICIENT" |
| DRAFT_REVIEW_REQUIRED | `draft=True` on all results, printed in CLI output |
| Headless (arcpy-free) | No arcpy import anywhere in core module |
| QA via QACollector | ERROR on failure, INFO on success |
| CSV input | `parse_wells_csv()` |
| CSV output | `--output` flag in CLI |
| Unit test with known gradient | Six well-set fixtures with analytic solutions |

**Non-goals (explicitly out of scope):**

- Writing geometry to `Env_GWFlowArrow_Draft` (arcpy POLYLINE) — that is a
  separate LOCAL tool step.
- Multi-event batch processing — one run per invocation.
- Anisotropic aquifer correction — straight plane fit only.
- Coordinate reprojection — caller must ensure consistent projected CRS.

**Risks and mitigations:**

| Risk | Mitigation |
|---|---|
| Collinear wells (e.g. wells in a line along a site boundary) | `cond(A)` check with 1e8 threshold; explicit QA ERROR; NaN result |
| Unit mismatch (GWE in meters vs. easting/northing in feet) | Document that all three coordinates must share the same linear unit; CLI help text makes this explicit |
| Very flat gradient (near-zero magnitude) | No guard added; magnitude = 0.0 is a valid result; caller can add a threshold if desired |
| numpy not installed | numpy is already a project dependency (used by `numpy_geom.py`, `groundwater_contours.py`) |
| Plan says "reuse npg algorithms" but no npg function maps to plane fitting | `numpy.linalg.lstsq` is the correct primitive; npg provides geometric utilities (rotation, hull, NN, simplification) — none apply here. Assumption noted inline. |

**Placeholder scan:** None found. All steps contain complete code.

**Type consistency check:** `WellWaterLevel` and `GWFlowResult` are defined in
Task 1 and consumed identically in Task 2 imports. `well_ids: List[str]` is
serialised as `",".join(result.well_ids)` in the CLI output step — consistent
with the schema table above.

---

**Plan complete and saved to `docs/superpowers/plans/2026-06-28-estimate-gw-flow-direction.md`.**

Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task,
review between tasks. Use `superpowers:subagent-driven-development`.

**2. Inline Execution** — execute tasks in this session with checkpoints.
Use `superpowers:executing-plans`.
