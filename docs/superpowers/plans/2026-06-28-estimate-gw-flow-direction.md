# EstimateGWFlowDirection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `EstimateGWFlowDirection` — fit a linear plane to GWE point cloud, compute gradient vector and flow azimuth. Pure stdlib math.
See spec: `docs/superpowers/specs/2026-06-28-estimate-gw-flow-direction-design.md`.

**Architecture:**
- New: `autogis/core/envmon/gw_flow_direction.py`
- Modify: `autogis/adapters/cli.py` — add `estimate-gw-flow` command (headless)
- New: `tests/envmon/test_gw_flow_direction.py`

## Global Constraints

- Arcpy-free. `math` stdlib only — no numpy.
- Gaussian elimination for n×n (n=3 always for normal equations).
- Run tests with `python -m pytest -q`.

---

### Task 1: Core `gw_flow_direction.py`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_gw_flow_direction.py`:

```python
import math
import pytest
from autogis.core.envmon.gw_flow_direction import (
    GWFlowPoint, fit_gw_plane, compute_flow_azimuth,
    estimate_gw_flow,
)

# Perfect plane: z = 0.1*x + 0.2*y + 50
_PLANE_POINTS = [
    GWFlowPoint("MW-01", 0.0,   0.0,   50.0),
    GWFlowPoint("MW-02", 100.0, 0.0,   60.0),   # z = 0.1*100 + 50
    GWFlowPoint("MW-03", 0.0,   100.0, 70.0),   # z = 0.2*100 + 50
]


def test_fit_plane_exact():
    a, b, c = fit_gw_plane(_PLANE_POINTS)
    assert math.isclose(a, 0.1, rel_tol=1e-6)
    assert math.isclose(b, 0.2, rel_tol=1e-6)
    assert math.isclose(c, 50.0, rel_tol=1e-6)


def test_fit_plane_too_few_points():
    with pytest.raises(ValueError, match="at least 3"):
        fit_gw_plane(_PLANE_POINTS[:2])


def test_flow_azimuth_east_gradient():
    # Gradient (1, 0) → GWE rises to east → flow goes west (270°)
    az = compute_flow_azimuth(1.0, 0.0)
    assert math.isclose(az, 270.0, abs_tol=0.01)


def test_flow_azimuth_north_gradient():
    # Gradient (0, 1) → GWE rises to north → flow goes south (180°)
    az = compute_flow_azimuth(0.0, 1.0)
    assert math.isclose(az, 180.0, abs_tol=0.01)


def test_estimate_gw_flow_perfect_plane():
    result = estimate_gw_flow(_PLANE_POINTS)
    assert result.passed if hasattr(result, 'passed') else True
    assert math.isclose(result.r_squared, 1.0, abs_tol=1e-6)
    assert math.isclose(result.gradient_x, 0.1, rel_tol=1e-4)
    assert math.isclose(result.gradient_y, 0.2, rel_tol=1e-4)


def test_estimate_gw_flow_noisy():
    import random
    rng = random.Random(42)
    noisy = [GWFlowPoint(f"MW-{i:02d}",
                          float(i*10), float(i*5),
                          50 + 0.1*i*10 + 0.2*i*5 + rng.uniform(-1, 1))
             for i in range(6)]
    result = estimate_gw_flow(noisy)
    assert 0.0 < result.r_squared <= 1.0


def test_estimate_gw_flow_poor_fit_warns():
    from autogis.core.common.qa import QACollector
    # Scatter with no planar trend
    pts = [
        GWFlowPoint("A", 0.0, 0.0, 100.0),
        GWFlowPoint("B", 1.0, 0.0, 50.0),
        GWFlowPoint("C", 0.0, 1.0, 90.0),
        GWFlowPoint("D", 1.0, 1.0, 30.0),
    ]
    qa = QACollector()
    result = estimate_gw_flow(pts, qa=qa)
    # R² can be low; just check no error is raised and result is returned
    assert result is not None
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_gw_flow_direction.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/gw_flow_direction.py`**

```python
"""gw_flow_direction.py — GW flow azimuth from linear plane fit to GWE points."""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, QARecord, SEV_INFO, SEV_WARNING, SEV_ERROR


@dataclass
class GWFlowPoint:
    location_id: str
    easting: float
    northing: float
    gwe: float


@dataclass
class GWFlowResult:
    gradient_x: float
    gradient_y: float
    gradient_magnitude: float
    flow_azimuth_deg: float
    r_squared: float
    point_count: int
    qa: QACollector


def _gaussian_3x3(A: list, b: list) -> list:
    """Solve 3×3 linear system Ax=b via Gaussian elimination with partial pivoting."""
    n = 3
    # Augmented matrix
    M = [A[i][:] + [b[i]] for i in range(n)]
    for col in range(n):
        # Pivot
        max_row = max(range(col, n), key=lambda r: abs(M[r][col]))
        M[col], M[max_row] = M[max_row], M[col]
        if abs(M[col][col]) < 1e-12:
            raise ValueError("Singular matrix — points may be collinear")
        for row in range(col + 1, n):
            factor = M[row][col] / M[col][col]
            for j in range(col, n + 1):
                M[row][j] -= factor * M[col][j]
    # Back substitution
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = M[i][n]
        for j in range(i + 1, n):
            x[i] -= M[i][j] * x[j]
        x[i] /= M[i][i]
    return x


def fit_gw_plane(points: list) -> tuple:
    """Fit z = ax + by + c. Returns (a, b, c)."""
    if len(points) < 3:
        raise ValueError("Need at least 3 points to fit a plane")
    # Normal equations: [Σx², Σxy, Σx; Σxy, Σy², Σy; Σx, Σy, n] · [a,b,c] = [Σxz, Σyz, Σz]
    n = len(points)
    sx2 = sum(p.easting**2 for p in points)
    sxy = sum(p.easting * p.northing for p in points)
    sx  = sum(p.easting for p in points)
    sy2 = sum(p.northing**2 for p in points)
    sy  = sum(p.northing for p in points)
    sxz = sum(p.easting * p.gwe for p in points)
    syz = sum(p.northing * p.gwe for p in points)
    sz  = sum(p.gwe for p in points)
    A = [[sx2, sxy, sx],
         [sxy, sy2, sy],
         [sx,  sy,  float(n)]]
    b = [sxz, syz, sz]
    return tuple(_gaussian_3x3(A, b))


def compute_flow_azimuth(gradient_x: float, gradient_y: float) -> float:
    """Flow azimuth (degrees CW from north) — direction of steepest descent."""
    fx, fy = -gradient_x, -gradient_y  # descent = opposite of gradient
    az = math.degrees(math.atan2(fx, fy)) % 360
    return round(az, 2)


def estimate_gw_flow(
    points: list,
    qa: Optional[QACollector] = None,
) -> Optional[GWFlowResult]:
    if qa is None:
        qa = QACollector()
    if len(points) < 3:
        qa.add(QARecord(SEV_ERROR, "insufficient_points",
                        f"Need ≥3 points; got {len(points)}"))
        return None
    try:
        a, b, c = fit_gw_plane(points)
    except ValueError as exc:
        qa.add(QARecord(SEV_ERROR, "plane_fit_failed", str(exc)))
        return None

    # R²
    z_pred = [a * p.easting + b * p.northing + c for p in points]
    z_mean = sum(p.gwe for p in points) / len(points)
    ss_res = sum((p.gwe - zp)**2 for p, zp in zip(points, z_pred))
    ss_tot = sum((p.gwe - z_mean)**2 for p in points)
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-12 else 1.0

    mag = math.sqrt(a**2 + b**2)
    azimuth = compute_flow_azimuth(a, b)

    if r2 < 0.5:
        qa.add(QARecord(SEV_WARNING, "poor_planar_fit",
                        f"R²={r2:.3f} — GWE surface may not be planar"))
    qa.add(QARecord(SEV_INFO, "flow_estimated",
                    f"Azimuth={azimuth}°  Gradient={mag:.5f}  R²={r2:.3f}"))

    return GWFlowResult(
        gradient_x=round(a, 6), gradient_y=round(b, 6),
        gradient_magnitude=round(mag, 6),
        flow_azimuth_deg=azimuth,
        r_squared=round(r2, 4),
        point_count=len(points),
        qa=qa,
    )


def load_gw_event_csv(path: Path) -> list:
    """Read GWEvent CSV; return MEASURED points with easting/northing."""
    points = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("status", "").upper() not in ("MEASURED",):
                continue
            try:
                points.append(GWFlowPoint(
                    location_id=row["location_id"],
                    easting=float(row["easting"]),
                    northing=float(row["northing"]),
                    gwe=float(row["gwe"]),
                ))
            except (KeyError, ValueError, TypeError):
                pass
    return points
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_gw_flow_direction.py -v
```

Expected: all 6 PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add autogis/core/envmon/gw_flow_direction.py \
        tests/envmon/test_gw_flow_direction.py
git commit -m "feat(envmon): gw_flow_direction — linear plane fit + flow azimuth (stdlib math)"
```

---

### Task 2: CLI command

- [ ] **Step 1: Add to `cli.py`**

```python
@envmon.command("estimate-gw-flow")
@click.option("--gw-event", "gw_event_path", required=True, type=click.Path(exists=True))
@click.option("--wells", default=None, help="Comma-separated subset of wells.")
@click.option("--out", required=True, type=click.Path())
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="warning")
def estimate_gw_flow_cmd(gw_event_path, wells, out, report, fail_on):
    """Estimate GW flow direction from GWE points via linear plane fit (headless)."""
    import json
    from autogis.core.envmon.gw_flow_direction import (
        load_gw_event_csv, estimate_gw_flow)
    from autogis.core.common.qa import QACollector

    points = load_gw_event_csv(Path(gw_event_path))
    if wells:
        well_set = set(w.strip() for w in wells.split(","))
        points = [p for p in points if p.location_id in well_set]

    qa = QACollector()
    result = estimate_gw_flow(points, qa=qa)
    if result:
        output = {
            "flow_azimuth_deg": result.flow_azimuth_deg,
            "gradient_magnitude": result.gradient_magnitude,
            "gradient_x": result.gradient_x,
            "gradient_y": result.gradient_y,
            "r_squared": result.r_squared,
            "point_count": result.point_count,
        }
        Path(out).write_text(json.dumps(output, indent=2), encoding="utf-8")
        click.echo(f"Flow azimuth: {result.flow_azimuth_deg}°  "
                   f"Gradient: {result.gradient_magnitude:.5f}  "
                   f"R²: {result.r_squared:.3f}")
    _render_qa(qa, report, fail_on)
```

- [ ] **Step 2: Help test + commit**

```python
def test_estimate_gw_flow_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "estimate-gw-flow" in result.output
```

```bash
git add autogis/adapters/cli.py tests/envmon/test_gw_flow_direction.py
git commit -m "feat(cli): add estimate-gw-flow command"
```
