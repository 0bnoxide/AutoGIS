"""Drone GCP checkpoint accuracy QA (Tool 11.1).

Reads a checkpoint CSV and evaluates horizontal and vertical RMS errors
against configurable thresholds. No arcpy dependency.
"""
from __future__ import annotations

import csv
import dataclasses
import math
from pathlib import Path
from typing import List

from autogis.core.common.qa import QACollector, SEV_ERROR, SEV_INFO, SEV_WARNING


@dataclasses.dataclass
class CheckpointRecord:
    """Input: one GCP checkpoint comparison row."""
    gcp_id: str
    expected_x: float
    expected_y: float
    expected_z: float
    measured_x: float
    measured_y: float
    measured_z: float


@dataclasses.dataclass
class CheckpointResult:
    """Per-point computed QA result."""
    gcp_id: str
    delta_x: float
    delta_y: float
    delta_z: float
    horizontal_error: float   # sqrt(dx^2 + dy^2)
    vertical_error: float     # abs(dz)
    point_pass: bool          # True if both errors <= respective thresholds


@dataclasses.dataclass
class CheckpointQASummary:
    """Aggregate QA result for all checkpoints."""
    n_points: int
    hrms: float               # horizontal root mean square error
    vrms: float               # vertical root mean square error
    hrms_threshold: float
    vrms_threshold: float
    hrms_pass: bool
    vrms_pass: bool
    overall_pass: bool
    results: List[CheckpointResult]


def read_checkpoint_csv(path: Path) -> List[CheckpointRecord]:
    """Read checkpoint CSV into CheckpointRecord list.

    Expected columns: gcp_id, expected_x, expected_y, expected_z,
                      measured_x, measured_y, measured_z
    """
    records = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            records.append(CheckpointRecord(
                gcp_id=row["gcp_id"],
                expected_x=float(row["expected_x"]),
                expected_y=float(row["expected_y"]),
                expected_z=float(row["expected_z"]),
                measured_x=float(row["measured_x"]),
                measured_y=float(row["measured_y"]),
                measured_z=float(row["measured_z"]),
            ))
    return records


def evaluate_gcp_checkpoints(
    checkpoints: List[CheckpointRecord],
    *,
    hrms_threshold: float = 0.05,
    vrms_threshold: float = 0.10,
    qa: QACollector,
) -> CheckpointQASummary:
    """Evaluate GCP checkpoint accuracy against RMS error thresholds.

    Args:
        checkpoints: List of CheckpointRecord from read_checkpoint_csv().
        hrms_threshold: Horizontal RMS error threshold in metres (default 0.05).
        vrms_threshold: Vertical RMS error threshold in metres (default 0.10).
        qa: QACollector for status messages and threshold exceedance warnings.

    Returns:
        CheckpointQASummary with per-point results and aggregate RMS values.
    """
    if not checkpoints:
        qa.add(SEV_ERROR, "no_checkpoints", "No checkpoint records provided.")
        return CheckpointQASummary(
            n_points=0,
            hrms=0.0, vrms=0.0,
            hrms_threshold=hrms_threshold, vrms_threshold=vrms_threshold,
            hrms_pass=False, vrms_pass=False,
            overall_pass=False, results=[],
        )

    results: List[CheckpointResult] = []
    for cp in checkpoints:
        dx = cp.measured_x - cp.expected_x
        dy = cp.measured_y - cp.expected_y
        dz = cp.measured_z - cp.expected_z
        herr = math.sqrt(dx ** 2 + dy ** 2)
        verr = abs(dz)
        results.append(CheckpointResult(
            gcp_id=cp.gcp_id,
            delta_x=dx, delta_y=dy, delta_z=dz,
            horizontal_error=herr,
            vertical_error=verr,
            point_pass=(herr <= hrms_threshold and verr <= vrms_threshold),
        ))

    n = len(results)
    hrms = math.sqrt(sum(r.horizontal_error ** 2 for r in results) / n)
    vrms = math.sqrt(sum(r.vertical_error ** 2 for r in results) / n)

    hrms_pass = hrms <= hrms_threshold
    vrms_pass = vrms <= vrms_threshold

    if not hrms_pass:
        qa.add(
            SEV_ERROR, "hrms_exceeds_threshold",
            f"Horizontal RMSE {hrms:.4f} m exceeds threshold {hrms_threshold} m "
            f"({n} checkpoint(s))",
        )
    if not vrms_pass:
        qa.add(
            SEV_ERROR, "vrms_exceeds_threshold",
            f"Vertical RMSE {vrms:.4f} m exceeds threshold {vrms_threshold} m "
            f"({n} checkpoint(s))",
        )

    n_fail = sum(1 for r in results if not r.point_pass)
    if n_fail:
        qa.add(
            SEV_WARNING, "individual_points_fail",
            f"{n_fail} of {n} checkpoint(s) exceed at least one threshold.",
        )

    qa.add(
        SEV_INFO, "checkpoint_qa_complete",
        f"GCP QA: {n} point(s), HRMS={hrms:.4f} m, VRMS={vrms:.4f} m — "
        f"H {'PASS' if hrms_pass else 'FAIL'}, V {'PASS' if vrms_pass else 'FAIL'}",
    )
    return CheckpointQASummary(
        n_points=n,
        hrms=hrms, vrms=vrms,
        hrms_threshold=hrms_threshold, vrms_threshold=vrms_threshold,
        hrms_pass=hrms_pass, vrms_pass=vrms_pass,
        overall_pass=hrms_pass and vrms_pass,
        results=results,
    )


def write_results_csv(summary: CheckpointQASummary, output_path: Path) -> None:
    """Write per-point CheckpointResult rows to CSV."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [f.name for f in dataclasses.fields(CheckpointResult)]
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for r in summary.results:
            writer.writerow(dataclasses.asdict(r))
