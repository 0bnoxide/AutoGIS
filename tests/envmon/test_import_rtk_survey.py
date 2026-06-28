import csv
from pathlib import Path
from autogis.core.envmon.import_rtk_survey import (
    RTKPoint, RTKColumnMap, parse_rtk_csv, assign_qa_flags,
)

_CSV_CONTENT = """\
PointID,Northing,Easting,Elevation_ft,FeatureCode,Description,HRMS_ft,VRMS_ft,FixType,CollectedAt,Operator
MW-01,4527893.12,293847.55,512.34,WELL,Monitoring Well,0.01,0.02,RTK_FIXED,2026-06-15,Alice
MW-02,4527750.00,293900.00,509.12,WELL,Monitoring Well,0.05,0.08,RTK_FLOAT,2026-06-15,Alice
INV001,4527800.00,293870.00,510.00,INV,Invalid high precision,0.50,0.80,AUTONOMOUS,2026-06-15,Alice
"""


def _write_csv(tmp_path, content=_CSV_CONTENT):
    p = tmp_path / "rtk.csv"
    p.write_text(content, encoding="utf-8")
    return p


def test_parse_rtk_csv_count(tmp_path):
    points = parse_rtk_csv(_write_csv(tmp_path))
    assert len(points) == 3


def test_parse_rtk_csv_northing(tmp_path):
    points = parse_rtk_csv(_write_csv(tmp_path))
    assert abs(points[0].northing - 4527893.12) < 0.001


def test_parse_rtk_csv_point_id(tmp_path):
    points = parse_rtk_csv(_write_csv(tmp_path))
    assert points[0].point_id == "MW-01"


def test_assign_qa_flags_fixed_no_flags(tmp_path):
    points = parse_rtk_csv(_write_csv(tmp_path))
    mw01 = next(p for p in points if p.point_id == "MW-01")
    flags = assign_qa_flags(mw01, hrms_threshold_ft=0.03, vrms_threshold_ft=0.05)
    assert flags == []


def test_assign_qa_flags_poor_hrms(tmp_path):
    points = parse_rtk_csv(_write_csv(tmp_path))
    mw02 = next(p for p in points if p.point_id == "MW-02")
    flags = assign_qa_flags(mw02, hrms_threshold_ft=0.03, vrms_threshold_ft=0.05)
    assert "hrms_exceeds_threshold" in flags


def test_assign_qa_flags_autonomous_fix(tmp_path):
    points = parse_rtk_csv(_write_csv(tmp_path))
    inv = next(p for p in points if p.point_id == "INV001")
    flags = assign_qa_flags(inv, hrms_threshold_ft=0.10, vrms_threshold_ft=0.10)
    assert "fix_type_not_rtk" in flags


def test_custom_column_map(tmp_path):
    content = "ID,Y,X,Z,Code\nMW-01,4527893.12,293847.55,512.34,WELL\n"
    p = tmp_path / "custom.csv"
    p.write_text(content, encoding="utf-8")
    cm = RTKColumnMap(point_id="ID", northing="Y", easting="X",
                      elevation_ft="Z", feature_code="Code")
    points = parse_rtk_csv(p, column_map=cm)
    assert len(points) == 1
    assert points[0].northing == 4527893.12


def test_import_rtk_survey_in_help():
    from click.testing import CliRunner
    from autogis.adapters.cli import autogis
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "import-rtk-survey" in result.output
