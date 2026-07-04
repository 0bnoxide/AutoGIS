import csv
from pathlib import Path

import pytest

from autogis.core.common.qa import QACollector
from autogis.core.envmon.import_rtk_survey import (
    RTKPoint, RTKColumnMap, parse_rtk_csv, assign_qa_flags,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "rtk"
_BROADWATER_PATH = Path(r"C:\Users\ichbi\OneDrive\Desktop\AutoGIS\BroadWATER2059.csv")

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


# --------------------------------------------------------------------------
# Headerless format detection (2026-07-03 design)
# --------------------------------------------------------------------------

_HEADERLESS_5COL_CONFIDENT = """\
1,558281.5482,2206038.3110,3224.0823,PT-1
2,558300.1200,2206050.4400,3225.1000,PT-2
"""

_HEADERLESS_5COL_AMBIGUOUS = """\
1,555000.12,545000.34,510.50,PT-1
2,556000.00,546000.00,511.00,PT-2
"""

_HEADERLESS_MALFORMED_7COL = """\
1,558281.5482,2206038.3110,3224.0823,PT-1,extra1,extra2
"""


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_headerless_5col_is_not_treated_as_header(tmp_path):
    points = parse_rtk_csv(_write(tmp_path, "hl5.csv", _HEADERLESS_5COL_CONFIDENT))
    assert len(points) == 2


def test_headerless_5col_confident_order_and_warning(tmp_path):
    qa = QACollector()
    points = parse_rtk_csv(_write(tmp_path, "hl5.csv", _HEADERLESS_5COL_CONFIDENT), qa=qa)
    assert points[0].point_id == "1"
    assert points[0].easting == pytest.approx(558281.5482)
    assert points[0].northing == pytest.approx(2206038.3110)
    assert points[0].description == "PT-1"
    assert any(r.category == "guessed_coord_order" for r in qa.records)


def test_headerless_5col_ambiguous_magnitude_raises(tmp_path):
    p = _write(tmp_path, "amb.csv", _HEADERLESS_5COL_AMBIGUOUS)
    with pytest.raises(ValueError, match="--format"):
        parse_rtk_csv(p)


def test_headerless_5col_explicit_pnezd_bypasses_guess(tmp_path):
    p = _write(tmp_path, "amb.csv", _HEADERLESS_5COL_AMBIGUOUS)
    qa = QACollector()
    points = parse_rtk_csv(p, coord_format="pnezd", qa=qa)
    assert points[0].northing == pytest.approx(555000.12)
    assert points[0].easting == pytest.approx(545000.34)
    assert not any(r.category == "guessed_coord_order" for r in qa.records)


def test_headerless_5col_explicit_penzd_bypasses_guess(tmp_path):
    p = _write(tmp_path, "amb.csv", _HEADERLESS_5COL_AMBIGUOUS)
    points = parse_rtk_csv(p, coord_format="penzd")
    assert points[0].easting == pytest.approx(555000.12)
    assert points[0].northing == pytest.approx(545000.34)


def test_headerless_11col_extended_layout():
    points = parse_rtk_csv(_FIXTURES / "extended_11col_sample.csv")
    assert len(points) == 1
    pt = points[0]
    assert pt.point_id == "1"
    assert pt.easting == pytest.approx(558281.5482)
    assert pt.northing == pytest.approx(2206038.3110)
    assert pt.elevation_ft == pytest.approx(3224.0823)
    assert pt.description == "MW-5R"
    assert pt.hrms_ft == pytest.approx(0.011)
    assert pt.vrms_ft == pytest.approx(0.019)
    assert pt.pdop == pytest.approx(1.2)
    assert pt.satellites == 22
    assert pt.fix_type == "RTK_FIXED"  # normalized from "FIXED"
    assert pt.collected_at == "14:23:10"


def test_fix_type_normalization_variants(tmp_path):
    content = (
        "1,558281.55,2206038.31,3224.08,A,,,,,FIXED,\n"
        "2,558290.55,2206040.31,3225.08,B,,,,,float,\n"
        "3,558295.55,2206045.31,3226.08,C,,,,,nrtk,\n"
        "4,558298.55,2206048.31,3227.08,D,,,,,DGPS,\n"
    )
    points = parse_rtk_csv(_write(tmp_path, "fix.csv", content))
    assert points[0].fix_type == "RTK_FIXED"
    assert points[1].fix_type == "RTK_FLOAT"
    assert points[2].fix_type == "NETWORK_RTK"
    assert points[3].fix_type == "DGPS"
    assert "fix_type_not_rtk" in assign_qa_flags(points[3])
    assert assign_qa_flags(points[0]) == []


def test_extra_columns_override_non_11col(tmp_path):
    content = "1,558281.55,2206038.31,3224.08,PT-1,0.02,0.03\n"
    p = _write(tmp_path, "custom7.csv", content)
    points = parse_rtk_csv(p, extra_columns=["hrms_ft", "vrms_ft"])
    assert points[0].hrms_ft == pytest.approx(0.02)
    assert points[0].vrms_ft == pytest.approx(0.03)


def test_extra_columns_count_mismatch_raises_not_silently_drops(tmp_path):
    # File has 2 trailing columns (0.02, 0.03); naming only 1 must not
    # silently discard the other -- it must error.
    content = "1,558281.55,2206038.31,3224.08,PT-1,0.02,0.03\n"
    p = _write(tmp_path, "custom7.csv", content)
    with pytest.raises(ValueError, match="count must match"):
        parse_rtk_csv(p, extra_columns=["hrms_ft"])


def test_non_numeric_coordinate_row_raises_with_row_context(tmp_path):
    # Row 2 has the correct column count but a non-numeric coordinate cell
    # (a plausible transcription error). Must name the row, not just
    # surface Python's bare "could not convert string to float" message.
    content = (
        "1,558281.5482,2206038.3110,3224.0823,PT-1\n"
        "2,N/A,2206050.4400,3225.1000,PT-2\n"
    )
    p = _write(tmp_path, "badnum.csv", content)
    with pytest.raises(ValueError, match=r"row 2"):
        parse_rtk_csv(p)


def test_ragged_row_raises_clear_error_not_indexerror(tmp_path):
    # Row 2 is missing its trailing description column -- a realistic
    # field-data typo (dropped trailing comma). Must not crash with a raw
    # IndexError; must raise a clear, catchable ValueError instead.
    content = (
        "1,558281.5482,2206038.3110,3224.0823,PT-1\n"
        "2,558300.1200,2206050.4400\n"
    )
    p = _write(tmp_path, "ragged.csv", content)
    with pytest.raises(ValueError, match="ragged"):
        parse_rtk_csv(p)


def test_extra_columns_unrecognized_field_raises(tmp_path):
    content = "1,558281.55,2206038.31,3224.08,PT-1,0.02\n"
    p = _write(tmp_path, "custom6.csv", content)
    with pytest.raises(ValueError, match="unrecognized"):
        parse_rtk_csv(p, extra_columns=["bogus_field"])


def test_extra_columns_noop_on_5col_with_warning(tmp_path):
    p = _write(tmp_path, "hl5.csv", _HEADERLESS_5COL_CONFIDENT)
    qa = QACollector()
    points = parse_rtk_csv(p, extra_columns=["hrms_ft"], qa=qa)
    assert len(points) == 2
    assert any("no extra columns" in r.message.lower() or "nothing to map" in r.message.lower()
               for r in qa.records)


def test_malformed_column_count_no_extra_columns_raises(tmp_path):
    p = _write(tmp_path, "bad7.csv", _HEADERLESS_MALFORMED_7COL)
    with pytest.raises(ValueError, match="--extra-columns"):
        parse_rtk_csv(p)


def test_headered_csv_ignores_format_and_extra_columns_with_warning(tmp_path):
    qa = QACollector()
    points = parse_rtk_csv(_write_csv(tmp_path), coord_format="pnezd",
                            extra_columns=["hrms_ft"], qa=qa)
    assert len(points) == 3
    assert any(r.category == "format_options_ignored" for r in qa.records)


@pytest.mark.skipif(not _BROADWATER_PATH.exists(),
                    reason="real fixture only available on the dev machine "
                          "(C:\\Users\\ichbi\\OneDrive\\Desktop\\AutoGIS\\BroadWATER2059.csv)")
def test_broadwater_real_fixture_12_points():
    points = parse_rtk_csv(_BROADWATER_PATH)
    assert len(points) == 12
    # Count alone doesn't catch a Northing/Easting swap -- assert the actual
    # confirmed-real values for row 1 (MW-5R), the exact regression this
    # feature exists to prevent.
    mw5r = points[0]
    assert mw5r.point_id == "1"
    assert mw5r.description == "MW-5R"
    assert mw5r.easting == pytest.approx(558281.5482)
    assert mw5r.northing == pytest.approx(2206038.3110)
