# DroneGCPCheckpointQA — Implementation Plan

**Goal:** Add `envmon drone-checkpoint-qa` CLI command that validates drone Ground Control Point (GCP) checkpoint accuracy. Reads a checkpoint CSV (`gcp_id, expected_x, expected_y, expected_z, measured_x, measured_y, measured_z`), computes horizontal and vertical RMS errors per point and in aggregate, compares to configurable thresholds, and emits a QA report with PASS/FAIL status. Enables automated survey accuracy verification in CI or pre-processing pipelines. CLOUD runtime — stdlib math only.

**Architecture:** New module `autogis/core/envmon/drone_checkpoint_qa.py`. Core function `evaluate_gcp_checkpoints(checkpoints, *, hrms_threshold, vrms_threshold, qa) -> CheckpointQASummary`. Uses only `math` from stdlib. Three dataclasses: `CheckpointRecord` (input), `CheckpointResult` (per-point output), `CheckpointQASummary` (aggregate). CSV reader `read_checkpoint_csv()` included. CLOUD runtime — no arcpy.

**Tech stack:** Python 3.14, click, stdlib math/csv/dataclasses. Reuses: `QACollector` from `autogis/core/common/qa.py`.

## Global constraints
- `core/` and `adapters/` import without arcpy or arcgis present
- Use openpyxl for Excel (ADR-008) — this plan uses no Excel
- New CLI command added to TOOLS in `autogis/runtime/capabilities.py` as `Runtime.CLOUD`
- Run tests with: `python -m pytest -q`
- CLI command goes in `autogis/adapters/cli.py` under the `envmon` group

---

### Task 1: Create `autogis/core/envmon/drone_checkpoint_qa.py`

**Files:**
- Create: `autogis/core/envmon/drone_checkpoint_qa.py`

**Complete code:**

```python
"""Drone GCP checkpoint accuracy QA (Tool 11.1).

Reads a checkpoint CSV and evaluates horizontal and vertical RMS errors
against configurable thresholds. No arcpy dependency.
"""
from __future__ import annotations

import csv
import dataclasses
import math
from pathlib import Path
from typing import List, Optional

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
```

**Steps:**
- [ ] Create module file as shown above
- [ ] Verify `import autogis.core.envmon.drone_checkpoint_qa` works without arcpy

---

### Task 2: Write `tests/test_drone_checkpoint_qa.py`

**Files:**
- Create: `tests/test_drone_checkpoint_qa.py`

**Complete code:**

```python
"""Tests for drone GCP checkpoint accuracy QA (Tool 11.1)."""
import csv
import math
from pathlib import Path

import pytest

from autogis.core.common.qa import QACollector
from autogis.core.envmon.drone_checkpoint_qa import (
    CheckpointRecord,
    CheckpointQASummary,
    CheckpointResult,
    evaluate_gcp_checkpoints,
    read_checkpoint_csv,
    write_results_csv,
)


def _cp(gcp_id: str, dx: float = 0.0, dy: float = 0.0, dz: float = 0.0):
    """Create a CheckpointRecord with given measurement offsets."""
    return CheckpointRecord(
        gcp_id=gcp_id,
        expected_x=100.0, expected_y=200.0, expected_z=50.0,
        measured_x=100.0 + dx, measured_y=200.0 + dy, measured_z=50.0 + dz,
    )


def test_perfect_gcp():
    """Zero-error checkpoints should pass all thresholds."""
    qa = QACollector()
    result = evaluate_gcp_checkpoints([_cp("GCP-1")], qa=qa)
    assert result.overall_pass is True
    assert result.hrms == 0.0
    assert result.vrms == 0.0


def test_hrms_exceeds_threshold():
    qa = QACollector()
    result = evaluate_gcp_checkpoints(
        [_cp("GCP-1", dx=0.1, dy=0.1)],
        hrms_threshold=0.05,
        qa=qa,
    )
    assert result.hrms_pass is False
    assert result.overall_pass is False
    assert any(r.category == "hrms_exceeds_threshold" for r in qa.records)


def test_vrms_exceeds_threshold():
    qa = QACollector()
    result = evaluate_gcp_checkpoints(
        [_cp("GCP-1", dz=0.15)],
        vrms_threshold=0.10,
        qa=qa,
    )
    assert result.vrms_pass is False
    assert any(r.category == "vrms_exceeds_threshold" for r in qa.records)


def test_vrms_computation_symmetry():
    """Two points with equal vertical error -> vrms == that error."""
    qa = QACollector()
    result = evaluate_gcp_checkpoints(
        [_cp("GCP-1", dz=0.05), _cp("GCP-2", dz=0.05)],
        vrms_threshold=0.10,
        qa=qa,
    )
    assert abs(result.vrms - 0.05) < 1e-9
    assert result.vrms_pass is True


def test_hrms_computation():
    """Two points with (3,4,0) error each -> herr=5.0 -> hrms=5.0."""
    qa = QACollector()
    result = evaluate_gcp_checkpoints(
        [_cp("G1", dx=3.0, dy=4.0), _cp("G2", dx=3.0, dy=4.0)],
        hrms_threshold=10.0,
        qa=qa,
    )
    assert abs(result.hrms - 5.0) < 1e-9


def test_empty_checkpoints():
    qa = QACollector()
    result = evaluate_gcp_checkpoints([], qa=qa)
    assert result.overall_pass is False
    assert result.n_points == 0
    assert any(r.category == "no_checkpoints" for r in qa.records)


def test_point_pass_flag():
    """Individual points exceeding thresholds should have point_pass=False."""
    qa = QACollector()
    result = evaluate_gcp_checkpoints(
        [_cp("GCP-1", dx=0.01), _cp("GCP-2", dx=0.2)],
        hrms_threshold=0.05,
        qa=qa,
    )
    pass_flags = {r.gcp_id: r.point_pass for r in result.results}
    # GCP-1: herr ~0.01 <= 0.05 => pass; GCP-2: herr 0.2 > 0.05 => fail
    assert pass_flags["GCP-1"] is True
    assert pass_flags["GCP-2"] is False


def test_qa_info_emitted():
    qa = QACollector()
    evaluate_gcp_checkpoints([_cp("GCP-1")], qa=qa)
    assert any(r.category == "checkpoint_qa_complete" for r in qa.records)


def test_read_checkpoint_csv(tmp_path):
    csv_path = tmp_path / "checkpoints.csv"
    csv_path.write_text(
        "gcp_id,expected_x,expected_y,expected_z,"
        "measured_x,measured_y,measured_z\n"
        "GCP-1,100.0,200.0,50.0,100.01,200.01,50.02\n"
        "GCP-2,110.0,210.0,52.0,110.0,210.0,52.0\n",
        encoding="utf-8",
    )
    records = read_checkpoint_csv(csv_path)
    assert len(records) == 2
    assert records[0].gcp_id == "GCP-1"
    assert records[1].measured_z == 52.0


def test_write_results_csv(tmp_path):
    qa = QACollector()
    summary = evaluate_gcp_checkpoints(
        [_cp("GCP-1", dx=0.02, dz=0.03)], qa=qa,
    )
    out = tmp_path / "results.csv"
    write_results_csv(summary, out)
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "gcp_id" in text
    assert "GCP-1" in text
```

**Steps:**
- [ ] Write test file
- [ ] Run `python -m pytest tests/test_drone_checkpoint_qa.py -q` — expect ImportError
- [ ] Create `drone_checkpoint_qa.py` (Task 1)
- [ ] Run tests again — expect all pass

---

### Task 3: Wire CLI command in `autogis/adapters/cli.py`

**Files:**
- Modify: `autogis/adapters/cli.py`

**Complete command code:**

```python
@envmon.command("drone-checkpoint-qa")
@click.option("--checkpoints", "checkpoints_csv", required=True,
              type=click.Path(exists=True),
              help="Checkpoint CSV (gcp_id, expected_x/y/z, measured_x/y/z).")
@click.option("--hrms-threshold", type=float, default=0.05, show_default=True,
              help="Horizontal RMSE threshold in metres.")
@click.option("--vrms-threshold", type=float, default=0.10, show_default=True,
              help="Vertical RMSE threshold in metres.")
@click.option("--output", default=None, type=click.Path(),
              help="Optional CSV path for per-point results.")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error",
              show_default=True)
def drone_checkpoint_qa_cmd(
    checkpoints_csv, hrms_threshold, vrms_threshold, output, report, fail_on
):
    """Tool 11.1: evaluate GCP checkpoint accuracy (headless)."""
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.drone_checkpoint_qa import (
        evaluate_gcp_checkpoints,
        read_checkpoint_csv,
        write_results_csv,
    )

    checkpoints = read_checkpoint_csv(Path(checkpoints_csv))
    qa = QACollector()
    summary = evaluate_gcp_checkpoints(
        checkpoints,
        hrms_threshold=hrms_threshold,
        vrms_threshold=vrms_threshold,
        qa=qa,
    )

    click.echo(f"Checkpoints: {summary.n_points}")
    click.echo(f"HRMS: {summary.hrms:.4f} m  (threshold: {hrms_threshold} m)"
               f"  -> {'PASS' if summary.hrms_pass else 'FAIL'}")
    click.echo(f"VRMS: {summary.vrms:.4f} m  (threshold: {vrms_threshold} m)"
               f"  -> {'PASS' if summary.vrms_pass else 'FAIL'}")
    click.echo(f"Overall: {'PASS' if summary.overall_pass else 'FAIL'}")

    if output:
        write_results_csv(summary, Path(output))
        click.echo(f"Results written: {output}")

    _render_qa(qa, report, fail_on)

    if not summary.overall_pass:
        raise SystemExit(1)
```

**Steps:**
- [ ] Add command to `autogis/adapters/cli.py`
- [ ] Add `"drone-checkpoint-qa": Runtime.CLOUD` to `TOOLS` dict in `autogis/runtime/capabilities.py`
- [ ] Run `python -m pytest -q` — expect all pass
- [ ] Commit: `feat(envmon): drone-checkpoint-qa — GCP checkpoint accuracy QA (CLOUD)`

---

## Run commands

```bash
# TDD step 1: verify tests fail before module exists
python -m pytest tests/test_drone_checkpoint_qa.py -q

# TDD step 2: after creating drone_checkpoint_qa.py
python -m pytest tests/test_drone_checkpoint_qa.py -q

# TDD step 3: full suite
python -m pytest -q
```
