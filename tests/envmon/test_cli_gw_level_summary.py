"""CLI test for the headless gw-level-summary command."""
from datetime import date

from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.common.records_csv import read_records_csv, write_records_csv
from autogis.core.common.schema.survey import ElevationHistory
from autogis.core.envmon.gw_level_summary import GWLevelRow


def _elev(loc, elev, survey_date, superseded=False):
    return ElevationHistory(
        location_id=loc, elevation_type="surveyed", elevation=elev,
        vertical_datum="NAVD88", survey_date=survey_date,
        survey_method="differential", source_run_id="L1",
        approved_for_use=True, superseded=superseded)


def test_gw_level_summary_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert result.exit_code == 0
    assert "gw-level-summary" in result.output


def test_gw_level_summary_end_to_end(tmp_path):
    elevs = [
        _elev("MW-1", 100.0, date(2026, 4, 1)),
        _elev("MW-1", 100.5, date(2026, 1, 1)),
        _elev("MW-2", 98.0, date(2026, 4, 1), superseded=True),  # excluded
    ]
    elev_csv = tmp_path / "elev.csv"
    write_records_csv(elevs, elev_csv, record_class=ElevationHistory)

    toc_csv = tmp_path / "toc.csv"
    toc_csv.write_text("location_id,toc_elevation\nMW-1,105.0\n", encoding="utf-8")

    out = tmp_path / "summary.csv"
    result = CliRunner().invoke(autogis, [
        "envmon", "gw-level-summary",
        "--elevations-csv", str(elev_csv),
        "--output", str(out),
        "--event-date", "2026-04-01",
        "--toc-csv", str(toc_csv),
    ])
    assert result.exit_code == 0, result.output
    rows = read_records_csv(out, GWLevelRow)
    assert len(rows) == 1  # MW-2 superseded -> excluded (bool coercion works)
    assert rows[0].location_id == "MW-1"
    assert rows[0].depth_to_water == 5.0
    assert rows[0].trend == "DECLINING"
