"""Tests for RTK control-network check (rtk_control_check.py)."""
from autogis.core.common.qa import QACollector
from autogis.core.envmon.rtk_control_check import (
    ControlCheckPoint,
    evaluate_control_check,
    read_control_check_csv,
    write_results_csv,
)


def _cp(control_id: str, dx: float = 0.0, dy: float = 0.0, dz: float = 0.0):
    """Create a ControlCheckPoint with given surveyed offsets from published."""
    return ControlCheckPoint(
        control_id=control_id,
        published_x=1000.0, published_y=2000.0, published_z=500.0,
        surveyed_x=1000.0 + dx, surveyed_y=2000.0 + dy, surveyed_z=500.0 + dz,
    )


def test_perfect_control_point():
    qa = QACollector()
    summary = evaluate_control_check([_cp("CP-1")], qa=qa)
    assert summary.overall_pass is True
    assert summary.n_pass == 1
    assert summary.n_fail == 0
    assert summary.rmse_horizontal == 0.0


def test_single_failing_point_fails_whole_network():
    """Unlike an RMS gate, one bad control point invalidates overall_pass."""
    qa = QACollector()
    summary = evaluate_control_check(
        [_cp("CP-1"), _cp("CP-2"), _cp("CP-3", dx=0.5)],
        horizontal_tolerance_ft=0.05,
        qa=qa,
    )
    assert summary.n_pass == 2
    assert summary.n_fail == 1
    assert summary.overall_pass is False
    assert any(r.category == "control_point_fails_tolerance" for r in qa.records)


def test_vertical_tolerance_checked_independently():
    qa = QACollector()
    summary = evaluate_control_check(
        [_cp("CP-1", dz=0.2)],
        horizontal_tolerance_ft=0.05,
        vertical_tolerance_ft=0.10,
        qa=qa,
    )
    assert summary.overall_pass is False
    assert summary.results[0].point_pass is False
    assert abs(summary.results[0].vertical_distance - 0.2) < 1e-9


def test_rmse_computation():
    """Two points with (3,4,0) horizontal offset -> hdist=5.0 -> rmse_h=5.0."""
    qa = QACollector()
    summary = evaluate_control_check(
        [_cp("CP-1", dx=3.0, dy=4.0), _cp("CP-2", dx=3.0, dy=4.0)],
        horizontal_tolerance_ft=10.0,
        qa=qa,
    )
    assert abs(summary.rmse_horizontal - 5.0) < 1e-9


def test_empty_control_points():
    qa = QACollector()
    summary = evaluate_control_check([], qa=qa)
    assert summary.overall_pass is False
    assert summary.n_points == 0
    assert any(r.category == "no_control_points" for r in qa.records)


def test_qa_info_emitted_on_completion():
    qa = QACollector()
    evaluate_control_check([_cp("CP-1")], qa=qa)
    assert any(r.category == "control_check_complete" for r in qa.records)


def test_read_control_check_csv(tmp_path):
    csv_path = tmp_path / "control.csv"
    csv_path.write_text(
        "control_id,published_x,published_y,published_z,"
        "surveyed_x,surveyed_y,surveyed_z\n"
        "CP-1,1000.0,2000.0,500.0,1000.01,2000.01,500.02\n"
        "CP-2,1010.0,2010.0,502.0,1010.0,2010.0,502.0\n",
        encoding="utf-8",
    )
    points = read_control_check_csv(csv_path)
    assert len(points) == 2
    assert points[0].control_id == "CP-1"
    assert points[1].surveyed_z == 502.0


def test_write_results_csv(tmp_path):
    qa = QACollector()
    summary = evaluate_control_check([_cp("CP-1", dx=0.02, dz=0.03)], qa=qa)
    out = tmp_path / "results.csv"
    write_results_csv(summary, out)
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "control_id" in text
    assert "CP-1" in text
