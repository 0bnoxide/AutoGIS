# EstimateGWFlowDirection Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** EstimateGWFlowDirection (Phase 4 / Tool 4.3)
**Priority:** MEDIUM-HIGH — required for potentiometric figure annotations

---

## Problem

Potentiometric figures must show the inferred groundwater flow direction arrow.
This is currently estimated by hand — an analyst picks three wells, sketches the
gradient, and places a manual arrow. The estimate is not reproducible, not
documented, and changes between reporting periods without audit trail.

---

## Approach

**Chosen:** Three-point (or best-fit n-point) linear GW gradient method. Given
a set of (easting, northing, GWE) points from `Env_GWEvent`, fit a linear plane
(`z = ax + by + c`) using least-squares, extract the gradient vector `(a, b)`,
and report the flow azimuth (direction of steepest descent) and gradient
magnitude. Pure Python math — `math` + stdlib only (no numpy for the 3-point
case; least-squares via Gaussian elimination for n-point).

**Rejected: numpy/scipy.** Not a core dependency. The 3-point exact solution
and n-point normal-equations least-squares are straightforward to implement in
stdlib for the typical well counts (<50 points).

**Rejected: Absorbing into `build_gw_elevation_event.py`.** Flow direction is
post-event analysis, not event building. Separate module.

---

## Architecture

```
autogis/
  core/envmon/
    gw_flow_direction.py        ← NEW
  adapters/
    cli.py                      ← add estimate-gw-flow command (headless)
tests/envmon/
  test_gw_flow_direction.py     ← NEW
```

---

## Public API (`gw_flow_direction.py`)

```python
@dataclass
class GWFlowPoint:
    location_id: str
    easting: float
    northing: float
    gwe: float        # groundwater elevation (consistent units)

@dataclass
class GWFlowResult:
    gradient_x: float         # dz/dx (easting direction)
    gradient_y: float         # dz/dy (northing direction)
    gradient_magnitude: float # sqrt(gx² + gy²) — hydraulic gradient
    flow_azimuth_deg: float   # degrees clockwise from north, direction of flow
    r_squared: float          # goodness of fit (1.0 = perfect plane)
    point_count: int
    qa: QACollector

def fit_gw_plane(points: list[GWFlowPoint]) -> tuple[float, float, float]:
    """
    Fit z = ax + by + c to n≥3 points via normal equations (least squares).
    Returns (a, b, c). Raises ValueError if fewer than 3 points.
    """

def compute_flow_azimuth(gradient_x: float, gradient_y: float) -> float:
    """
    Convert gradient vector to flow azimuth (degrees CW from north).
    Flow is in direction of steepest descent: opposite of gradient.
    """

def estimate_gw_flow(
    points: list[GWFlowPoint],
    qa: QACollector | None = None,
) -> GWFlowResult:
    """
    Fit plane, compute gradient, azimuth, R².
    Adds QA warnings if R² < 0.5 (poor planar fit).
    """

def load_gw_event_csv(path: Path) -> list[GWFlowPoint]:
    """
    Read GWEvent CSV (from build-gw-event output).
    Required columns: LocationID, Easting, Northing, GWE.
    Only MEASURED status rows included.
    """
```

---

## Math

**Normal equations (least-squares plane):**

Given n points (xᵢ, yᵢ, zᵢ), solve A·[a,b,c]ᵀ = Bᵀ where:
```
A = [[Σx², Σxy, Σx],
     [Σxy, Σy², Σy],
     [Σx,  Σy,  n ]]
B = [Σxz, Σyz, Σz]
```

**Flow azimuth:**
```
grad = (a, b)  ← gradient of fitted plane
flow_dir = (-a, -b)  ← steepest descent
azimuth = atan2(flow_dir[0], flow_dir[1]) × 180/π  (mod 360)
```

**R²:** variance explained by plane vs. mean.

---

## CLI Command

```
autogis envmon estimate-gw-flow \
  --gw-event <env_gwevent.csv> \
  [--wells MW-01,MW-02,MW-03]  \  # optional subset for 3-point method
  --out <gw_flow.json> \
  [--report <qa.md>]
```

Output JSON: `{azimuth_deg, gradient_magnitude, gradient_x, gradient_y, r_squared, point_count}`.

Headless.

---

## Test Strategy

`tests/envmon/test_gw_flow_direction.py` — arcpy-free:

1. `fit_gw_plane` with 3 coplanar points → exact solution (zero residuals)
2. `compute_flow_azimuth(1, 0)` → flow is west (270°) — gradient east, descent west
3. `compute_flow_azimuth(0, 1)` → flow is south (180°)
4. `estimate_gw_flow` with perfect plane → R²=1.0
5. `estimate_gw_flow` with noisy points → R² < 1.0, no error raised
6. R² < 0.5 → WARNING `poor_planar_fit` in QA
7. Fewer than 3 points → QARecord ERROR, None returned
8. `load_gw_event_csv` filters out non-MEASURED rows
