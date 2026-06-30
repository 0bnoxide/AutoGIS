"""CLI test for the headless build-gwe-event command (Tool 4.1)."""
from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.common.records_csv import read_records_csv
from autogis.core.common.schema.envmon import EnvWaterLevelEvent


def test_build_gwe_event_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert result.exit_code == 0
    assert "build-gwe-event" in result.output


def test_build_gwe_event_end_to_end(tmp_path):
    wl = tmp_path / "wl.csv"
    wl.write_text(
        "site_id,location_id,gwe_ft,dtw_ft,status,measured_by\n"
        "S1,MW-1,100.0,10.0,OK,field\n"
        "S1,MW-2,100.2,9.8,OK,field\n"
        "S1,MW-3,100.1,9.9,Dry,field\n",
        encoding="utf-8")
    exclude = tmp_path / "exclude.txt"
    exclude.write_text("# off-network\nMW-2\n", encoding="utf-8")

    out = tmp_path / "gwe.csv"
    result = CliRunner().invoke(autogis, [
        "envmon", "build-gwe-event",
        "--water-levels", str(wl),
        "--event-date", "2026-06-15",
        "--out", str(out),
        "--exclude", str(exclude),
    ])
    assert result.exit_code == 0, result.output
    rows = read_records_csv(out, EnvWaterLevelEvent)
    by = {r.location_id: r for r in rows}
    assert by["MW-1"].use_for_model is True
    assert by["MW-2"].use_for_model is False   # excluded list
    assert by["MW-3"].use_for_model is False   # Dry
    assert "Dry" in by["MW-3"].exclusion_reason
