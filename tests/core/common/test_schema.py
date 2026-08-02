from __future__ import annotations
import dataclasses
from datetime import date, datetime

from autogis.core.common.schema import (
    EnvSample, EnvAnalyticalResult, EnvImportQA, EnvWaterLevelEvent,
    BoringLocation, LithologyInterval, BoringSample, WellConstruction,
    GroundwaterObservation, BoringPhoto, BoringComment,
    SurveyPointRaw, SurveyPointQA, LevelLoopRun, LevelLoopObservation,
    ElevationHistory,
    DroneFlight, DroneControlPoint, DroneCheckpoint, DroneProductRecord,
)


def test_env_sample_table_name():
    assert EnvSample.table_name == "Env_Samples"


def test_env_sample_to_row_keys():
    s = EnvSample(
        site_id="H281", location_id="MW-1", event_date=date(2026, 6, 1),
        matrix="GW", sample_id="H281-MW1-GW-2026Q2",
    )
    row = s.to_row()
    assert "site_id" in row
    assert "location_id" in row
    assert "event_date" in row
    assert "matrix" in row
    assert "sample_id" in row


def test_env_analytical_result_table_name():
    assert EnvAnalyticalResult.table_name == "Env_AnalyticalResults"


def test_env_import_qa_table_name():
    assert EnvImportQA.table_name == "Env_ImportQA"


def test_env_water_level_event_table_name():
    assert EnvWaterLevelEvent.table_name == "Env_CurrentWaterLevelEvent"


def test_boring_location_table_name():
    assert BoringLocation.table_name == "BoringLocations"


def test_boring_location_to_row_is_dict():
    b = BoringLocation(
        boring_id="B-01", site_id="H281", location_type="boring",
        northing=None, easting=None, ground_elevation=None,
        toc_elevation=None, status="drilled",
    )
    assert isinstance(b.to_row(), dict)


def test_lithology_interval_table_name():
    assert LithologyInterval.table_name == "LithologyIntervals"


def test_boring_sample_table_name():
    assert BoringSample.table_name == "BoringSamples"


def test_well_construction_table_name():
    assert WellConstruction.table_name == "WellConstruction"


def test_groundwater_observation_table_name():
    assert GroundwaterObservation.table_name == "GroundwaterObservations"


def test_boring_photo_table_name():
    assert BoringPhoto.table_name == "BoringPhotos"


def test_boring_comment_table_name():
    assert BoringComment.table_name == "BoringComments"


def test_survey_point_raw_table_name():
    assert SurveyPointRaw.table_name == "SurveyPoints_Raw"


def test_survey_point_raw_has_pdop_and_satellites():
    p = SurveyPointRaw(site_id="H281", batch_id="B1", point_id="MW-01",
                       northing=1.0, easting=2.0, elevation=3.0,
                       pdop=1.2, satellites=22)
    row = p.to_row()
    assert row["site_id"] == "H281"
    assert row["batch_id"] == "B1"
    assert row["pdop"] == 1.2
    assert row["satellites"] == 22


def test_survey_point_qa_table_name():
    assert SurveyPointQA.table_name == "SurveyPoints_QA"


def test_survey_point_qa_serializes_provenance():
    p = SurveyPointQA(
        site_id="H281", batch_id="B1", point_id="MW-01",
        qa_status="PASS", qa_flags=[])
    row = p.to_row()
    assert row["site_id"] == "H281"
    assert row["batch_id"] == "B1"


def test_level_loop_run_table_name():
    assert LevelLoopRun.table_name == "LevelLoopRuns"


def test_level_loop_observation_table_name():
    assert LevelLoopObservation.table_name == "LevelLoopObservations"


def test_elevation_history_table_name():
    assert ElevationHistory.table_name == "ElevationHistory"


def test_elevation_history_to_row():
    e = ElevationHistory(
        location_id="MW-1", elevation_type="TOC", elevation=4812.5,
        vertical_datum="NAVD88", survey_date=date(2026, 6, 1),
        survey_method="level_loop", source_run_id="abc123",
        approved_for_use=True, superseded=False,
    )
    row = e.to_row()
    assert row["approved_for_use"] is True
    assert row["superseded"] is False


def test_drone_flight_table_name():
    assert DroneFlight.table_name == "DroneFlights"


def test_drone_control_point_table_name():
    assert DroneControlPoint.table_name == "DroneControlPoints"


def test_drone_checkpoint_table_name():
    assert DroneCheckpoint.table_name == "DroneCheckpoints"


def test_drone_product_record_table_name():
    assert DroneProductRecord.table_name == "DroneProductRegistry"


def test_to_row_returns_all_fields():
    """to_row() must include every field — no silent omissions."""
    e = ElevationHistory(
        location_id="MW-1", elevation_type="TOC", elevation=4812.5,
        vertical_datum="NAVD88", survey_date=date(2026, 6, 1),
        survey_method="level_loop", source_run_id="abc123",
        approved_for_use=True, superseded=False,
    )
    expected_keys = {f.name for f in dataclasses.fields(e)}
    assert set(e.to_row().keys()) == expected_keys
