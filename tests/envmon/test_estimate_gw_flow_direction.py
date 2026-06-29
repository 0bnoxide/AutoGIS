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
