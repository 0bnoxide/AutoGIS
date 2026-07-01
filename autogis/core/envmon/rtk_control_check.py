"""RTK survey control-network check (headless).

Compares RTK-surveyed control shots against a published control-point /
benchmark database (known-good X/Y/Z) and reports per-point residuals plus
aggregate RMSE. Unlike DroneGCPCheckpointQA (photogrammetry convention: an
RMS-threshold gate tolerates a few outlier points), a survey control network
is only as good as its worst point, so ``overall_pass`` here requires *every*
point to pass its own tolerance — RMSE is reported for information only.

No arcpy dependency. Pure stdlib (``csv`` + ``math``).
"""
from __future__ import annotations

import csv
import dataclasses
import math
from pathlib import Path
from typing import List

from autogis.core.common.qa import QACollector, SEV_ERROR, SEV_INFO


@dataclasses.dataclass
class ControlCheckPoint:
    """Input: one control point with published (known) and surveyed values."""
    control_id: str
    published_x: float
    published_y: float
    published_z: float
    surveyed_x: float
    surveyed_y: float
    surveyed_z: float


@dataclasses.dataclass
class ControlCheckResult:
    """Per-point computed residuals."""
    control_id: str
    delta_x: float
    delta_y: float
    delta_z: float
    horizontal_distance: float   # sqrt(dx^2 + dy^2)
    vertical_distance: float     # abs(dz)
    point_pass: bool


@dataclasses.dataclass
class ControlCheckSummary:
    """Aggregate result for a control-network check."""
    n_points: int
    rmse_horizontal: float
    rmse_vertical: float
    horizontal_tolerance_ft: float
    vertical_tolerance_ft: float
    n_pass: int
    n_fail: int
    overall_pass: bool           # True only if every point passes
    results: List[ControlCheckResult]


def read_control_check_csv(path: Path) -> List[ControlCheckPoint]:
    """Read a control-check CSV into ControlCheckPoint rows.

    Expected columns: control_id, published_x, published_y, published_z,
                      surveyed_x, surveyed_y, surveyed_z
    """
    points = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            points.append(ControlCheckPoint(
                control_id=row["control_id"],
                published_x=float(row["published_x"]),
                published_y=float(row["published_y"]),
                published_z=float(row["published_z"]),
                surveyed_x=float(row["surveyed_x"]),
                surveyed_y=float(row["surveyed_y"]),
                surveyed_z=float(row["surveyed_z"]),
            ))
    return points


def evaluate_control_check(
    points: List[ControlCheckPoint],
    *,
    horizontal_tolerance_ft: float = 0.05,
    vertical_tolerance_ft: float = 0.10,
    qa: QACollector,
) -> ControlCheckSummary:
    """Evaluate RTK control shots against published benchmarks.

    Args:
        points: List of ControlCheckPoint from read_control_check_csv().
        horizontal_tolerance_ft: Max allowed horizontal distance, per point.
        vertical_tolerance_ft: Max allowed vertical distance, per point.
        qa: QACollector for status messages and per-point failures.

    Returns:
        ControlCheckSummary. overall_pass requires every point to pass —
        a single bad control point invalidates the network.
    """
    if not points:
        qa.add(SEV_ERROR, "no_control_points", "No control-check records provided.")
        return ControlCheckSummary(
            n_points=0,
            rmse_horizontal=0.0, rmse_vertical=0.0,
            horizontal_tolerance_ft=horizontal_tolerance_ft,
            vertical_tolerance_ft=vertical_tolerance_ft,
            n_pass=0, n_fail=0, overall_pass=False, results=[],
        )

    results: List[ControlCheckResult] = []
    for pt in points:
        dx = pt.surveyed_x - pt.published_x
        dy = pt.surveyed_y - pt.published_y
        dz = pt.surveyed_z - pt.published_z
        hdist = math.sqrt(dx ** 2 + dy ** 2)
        vdist = abs(dz)
        point_pass = hdist <= horizontal_tolerance_ft and vdist <= vertical_tolerance_ft
        results.append(ControlCheckResult(
            control_id=pt.control_id,
            delta_x=dx, delta_y=dy, delta_z=dz,
            horizontal_distance=hdist, vertical_distance=vdist,
            point_pass=point_pass,
        ))
        if not point_pass:
            qa.add(
                SEV_ERROR, "control_point_fails_tolerance",
                f"Control point {pt.control_id!r}: horizontal={hdist:.4f} ft "
                f"(tol {horizontal_tolerance_ft} ft), vertical={vdist:.4f} ft "
                f"(tol {vertical_tolerance_ft} ft)",
            )

    n = len(results)
    rmse_h = math.sqrt(sum(r.horizontal_distance ** 2 for r in results) / n)
    rmse_v = math.sqrt(sum(r.vertical_distance ** 2 for r in results) / n)
    n_pass = sum(1 for r in results if r.point_pass)
    n_fail = n - n_pass
    overall_pass = n_fail == 0

    qa.add(
        SEV_INFO, "control_check_complete",
        f"RTK control check: {n} point(s), {n_pass} pass / {n_fail} fail, "
        f"RMSE horizontal={rmse_h:.4f} ft, RMSE vertical={rmse_v:.4f} ft — "
        f"{'PASS' if overall_pass else 'FAIL'}",
    )
    return ControlCheckSummary(
        n_points=n,
        rmse_horizontal=rmse_h, rmse_vertical=rmse_v,
        horizontal_tolerance_ft=horizontal_tolerance_ft,
        vertical_tolerance_ft=vertical_tolerance_ft,
        n_pass=n_pass, n_fail=n_fail, overall_pass=overall_pass,
        results=results,
    )


def write_results_csv(summary: ControlCheckSummary, output_path: Path) -> None:
    """Write per-point ControlCheckResult rows to CSV."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [f.name for f in dataclasses.fields(ControlCheckResult)]
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for r in summary.results:
            writer.writerow(dataclasses.asdict(r))
