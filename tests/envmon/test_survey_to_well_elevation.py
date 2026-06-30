"""Tests for survey_to_well_elevation — headless selection + history records.

write_rtk_elevations_to_wells() is # pragma: no cover and NOT tested here.
"""
from datetime import date

from autogis.core.common.qa import QACollector
from autogis.core.envmon.import_rtk_survey import RTKPoint
from autogis.core.envmon.survey_to_well_elevation import (
    RTKElevationUpdatePlan,
    build_elevation_history_records,
    select_rtk_elevations_for_wells,
)

_POINTS_OK = [
    RTKPoint("MW-01", 4527893.12, 293847.55, 512.34,
             hrms_ft=0.01, vrms_ft=0.02, fix_type="RTK_FIXED"),
    RTKPoint("MW-02", 4527750.00, 293900.00, 509.12,
             hrms_ft=0.01, vrms_ft=0.02, fix_type="RTK_FIXED"),
]

_POINTS_FAIL_QA = [
    RTKPoint("MW-03", 4527700.00, 293850.00, 508.00,
             hrms_ft=0.15, vrms_ft=0.20, fix_type="AUTONOMOUS"),
]

_WELL_IDS_ALL = {"MW-01", "MW-02", "MW-03"}


# ---- select_rtk_elevations_for_wells ----------------------------------------

def test_select_returns_plan():
    qa = QACollector()
    plan = select_rtk_elevations_for_wells(_POINTS_OK, {"MW-01", "MW-02"}, "B-1", qa)
    assert isinstance(plan, RTKElevationUpdatePlan)
    assert set(plan.updates.keys()) == {"MW-01", "MW-02"}


def test_select_correct_elevation_values():
    qa = QACollector()
    plan = select_rtk_elevations_for_wells(_POINTS_OK, {"MW-01", "MW-02"}, "B-2", qa)
    assert abs(plan.updates["MW-01"] - 512.34) < 0.001
    assert abs(plan.updates["MW-02"] - 509.12) < 0.001


def test_failed_qa_points_excluded_from_updates():
    qa = QACollector()
    plan = select_rtk_elevations_for_wells(_POINTS_FAIL_QA, _WELL_IDS_ALL, "B-3", qa)
    assert "MW-03" not in plan.updates
    assert "MW-03" in plan.failed_qa


def test_failed_qa_emits_warning_records():
    qa = QACollector()
    select_rtk_elevations_for_wells(_POINTS_FAIL_QA, _WELL_IDS_ALL, "B-4", qa)
    assert any(r.severity == "WARNING" for r in qa.records)


def test_point_not_in_well_ids_goes_to_skipped():
    qa = QACollector()
    plan = select_rtk_elevations_for_wells(_POINTS_OK, {"MW-01"}, "B-5", qa)
    assert "MW-02" not in plan.updates
    assert "MW-02" in plan.skipped


def test_mixed_batch_all_buckets():
    all_points = _POINTS_OK + _POINTS_FAIL_QA
    qa = QACollector()
    plan = select_rtk_elevations_for_wells(all_points, {"MW-01"}, "B-6", qa)
    assert set(plan.updates.keys()) == {"MW-01"}
    assert "MW-02" in plan.skipped
    assert "MW-03" in plan.failed_qa


def test_empty_points_produces_empty_plan():
    qa = QACollector()
    plan = select_rtk_elevations_for_wells([], set(), "B-7", qa)
    assert plan.updates == {}
    assert plan.failed_qa == []
    assert plan.skipped == []


def test_qa_plan_complete_record_always_present():
    qa = QACollector()
    select_rtk_elevations_for_wells(_POINTS_OK, {"MW-01", "MW-02"}, "B-8", qa)
    assert any(r.category == "plan_complete" for r in qa.records)


def test_custom_hrms_threshold_tightens_qa():
    pts = [RTKPoint("MW-01", 4527893.12, 293847.55, 512.34,
                    hrms_ft=0.01, vrms_ft=0.02, fix_type="RTK_FIXED")]
    qa = QACollector()
    plan = select_rtk_elevations_for_wells(
        pts, {"MW-01"}, "B-9", qa,
        hrms_threshold_ft=0.005, vrms_threshold_ft=0.05)
    assert "MW-01" in plan.failed_qa
    assert "MW-01" not in plan.updates


def test_elevation_type_stored_on_plan():
    qa = QACollector()
    plan = select_rtk_elevations_for_wells(
        _POINTS_OK, {"MW-01", "MW-02"}, "B-10", qa, elevation_type="GS")
    assert plan.elevation_type == "GS"


# ---- build_elevation_history_records ----------------------------------------

def test_history_records_count_matches_updates():
    qa = QACollector()
    plan = select_rtk_elevations_for_wells(_POINTS_OK, {"MW-01", "MW-02"}, "B-11", qa)
    records = build_elevation_history_records(plan, date(2026, 6, 28))
    assert len(records) == 2


def test_history_records_survey_method_is_gps_rtk():
    qa = QACollector()
    plan = select_rtk_elevations_for_wells(_POINTS_OK, {"MW-01", "MW-02"}, "B-12", qa)
    records = build_elevation_history_records(plan, date(2026, 6, 28))
    assert all(r.survey_method == "GPS_RTK" for r in records)


def test_history_records_source_run_id_matches_batch():
    qa = QACollector()
    plan = select_rtk_elevations_for_wells(_POINTS_OK, {"MW-01", "MW-02"}, "MY-13", qa)
    records = build_elevation_history_records(plan, date(2026, 6, 28))
    assert all(r.source_run_id == "MY-13" for r in records)


def test_history_records_not_superseded_on_creation():
    qa = QACollector()
    plan = select_rtk_elevations_for_wells(_POINTS_OK, {"MW-01", "MW-02"}, "B-14", qa)
    records = build_elevation_history_records(plan, date(2026, 6, 28))
    assert all(r.superseded is False for r in records)


def test_history_records_elevation_type_propagates():
    qa = QACollector()
    plan = select_rtk_elevations_for_wells(
        _POINTS_OK, {"MW-01", "MW-02"}, "B-15", qa, elevation_type="TOC")
    records = build_elevation_history_records(plan, date(2026, 6, 28))
    assert all(r.elevation_type == "TOC" for r in records)


def test_history_records_vertical_datum_default():
    qa = QACollector()
    plan = select_rtk_elevations_for_wells(_POINTS_OK, {"MW-01", "MW-02"}, "B-16", qa)
    records = build_elevation_history_records(plan, date(2026, 6, 28))
    assert all(r.vertical_datum == "NAVD88" for r in records)


def test_history_records_approved_for_use_default_false():
    qa = QACollector()
    plan = select_rtk_elevations_for_wells(_POINTS_OK, {"MW-01", "MW-02"}, "B-17", qa)
    records = build_elevation_history_records(plan, date(2026, 6, 28))
    assert all(r.approved_for_use is False for r in records)


def test_empty_plan_produces_no_history_records():
    qa = QACollector()
    plan = select_rtk_elevations_for_wells([], set(), "B-18", qa)
    records = build_elevation_history_records(plan, date(2026, 6, 28))
    assert records == []


def test_sql_quote_escapes_single_quotes():
    from autogis.core.envmon.survey_to_well_elevation import sql_quote
    assert sql_quote("O'Brien") == "O''Brien"
    assert sql_quote("plain-id") == "plain-id"
