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
