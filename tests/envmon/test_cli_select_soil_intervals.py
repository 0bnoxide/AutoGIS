"""CLI test for the headless select-soil-intervals command (Tool 4.8)."""
from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.common.records_csv import read_records_csv
from autogis.core.envmon.soil_interval_selector import IntervalSelection


def test_select_soil_intervals_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert result.exit_code == 0
    assert "select-soil-intervals" in result.output


def test_select_soil_intervals_end_to_end(tmp_path):
    soil = tmp_path / "soil.csv"
    soil.write_text(
        "location_id,analyte,depth_top,depth_bottom,result_value,screening_level\n"
        "B-1,Pb,2,4,10,100\n"
        "B-1,As,2,4,5,1\n",
        encoding="utf-8")
    out = tmp_path / "sel.csv"
    result = CliRunner().invoke(autogis, [
        "envmon", "select-soil-intervals",
        "--soil-results", str(soil),
        "--rule", "highest_exceedance",
        "--out", str(out),
    ])
    assert result.exit_code == 0, result.output
    rows = read_records_csv(out, IntervalSelection)
    assert len(rows) == 1
    assert rows[0].analyte == "As"             # ratio 5 > 0.1
    assert rows[0].selection_rule == "highest_exceedance"
