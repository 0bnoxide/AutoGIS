"""Unit tests for gw_level_summary (Tool 5.1)."""
from datetime import date

import pytest

from autogis.core.common.qa import QACollector
from autogis.core.common.schema.survey import ElevationHistory
from autogis.core.envmon.gw_level_summary import build_gw_level_summary

D1, D2 = date(2026, 1, 1), date(2026, 4, 1)


def _elev(loc, elev, survey_date, approved=True, superseded=False):
    return ElevationHistory(
        location_id=loc, elevation_type="surveyed", elevation=elev,
        vertical_datum="NAVD88", survey_date=survey_date,
        survey_method="differential", source_run_id="L1",
        approved_for_use=approved, superseded=superseded)


def test_basic_summary():
    elevs = [_elev("MW-1", 100.0, D2), _elev("MW-1", 100.5, D1)]
    qa = QACollector()
    rows = build_gw_level_summary(elevs, {"MW-1": 105.0}, event_date=D2, qa=qa)
    assert len(rows) == 1
    r = rows[0]
    assert r.depth_to_water == pytest.approx(5.0)
    assert r.trend == "DECLINING"  # DTW increased (water dropped from 100.5->100.0)


def test_no_toc_no_dtw():
    elevs = [_elev("MW-1", 100.0, D2)]
    qa = QACollector()
    rows = build_gw_level_summary(elevs, {}, event_date=D2, qa=qa)
    assert rows[0].depth_to_water is None


def test_superseded_excluded():
    elevs = [_elev("MW-1", 99.0, D2, superseded=True)]
    qa = QACollector()
    rows = build_gw_level_summary(elevs, {}, event_date=D2, qa=qa)
    assert len(rows) == 0


def test_unapproved_excluded():
    elevs = [_elev("MW-1", 99.0, D2, approved=False)]
    qa = QACollector()
    rows = build_gw_level_summary(elevs, {}, event_date=D2, qa=qa)
    assert len(rows) == 0


def test_multiple_approved_warns():
    elevs = [_elev("MW-1", 100.0, D2), _elev("MW-1", 100.1, D2)]
    qa = QACollector()
    build_gw_level_summary(elevs, {}, event_date=D2, qa=qa)
    assert any(r.category == "multiple_approved_elevations" for r in qa.records)


def test_rising_trend():
    elevs = [_elev("MW-1", 99.0, D1), _elev("MW-1", 100.0, D2)]
    qa = QACollector()
    rows = build_gw_level_summary(elevs, {"MW-1": 105.0}, event_date=D2, qa=qa)
    assert rows[0].trend == "RISING"  # water level rose (DTW decreased)


def test_zero_toc_is_honored_not_treated_as_missing():
    """A TOC elevation of exactly 0.0 is a real datum, not 'no TOC' (#82 class)."""
    elevs = [_elev("MW-1", -5.0, D2)]
    qa = QACollector()
    rows = build_gw_level_summary(elevs, {"MW-1": 0.0}, event_date=D2, qa=qa)
    assert rows[0].toc_elevation == 0.0
    assert rows[0].depth_to_water == pytest.approx(5.0)  # 0.0 - (-5.0)


def test_insufficient_data_trend_when_no_history():
    elevs = [_elev("MW-1", 100.0, D2)]
    qa = QACollector()
    rows = build_gw_level_summary(elevs, {}, event_date=D2, qa=qa)
    assert rows[0].trend == "INSUFFICIENT_DATA"
