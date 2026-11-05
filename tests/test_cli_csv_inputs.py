"""CSV inputs that pass ``click.Path(exists=True)`` but cannot be read -- a
directory, a non-UTF-8 file -- are a clean CLI error, not a traceback (#573).
"""
import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis


@pytest.mark.parametrize(("command", "flag", "csv_body"), [
    (
        "drone-checkpoint-qa", "--checkpoints",
        "gcp_id,expected_x,expected_y,expected_z,measured_x,measured_y,measured_z\n"
        "GCP-1,1,2,3,1,2,3\n",
    ),
    (
        "rtk-control-check", "--control-points",
        "control_id,published_x,published_y,published_z,surveyed_x,surveyed_y,surveyed_z\n"
        "CP-1,1,2,3,1,2,3\n",
    ),
])
def test_checkpoint_commands_accept_utf8_bom_csv(tmp_path, command, flag, csv_body):
    csv_path = tmp_path / "excel-export.csv"
    csv_path.write_text(csv_body, encoding="utf-8-sig")

    result = CliRunner().invoke(autogis, ["envmon", command, flag, str(csv_path)])
    assert result.exit_code == 0, result.output
    assert "Overall: PASS" in result.output


def _bad_inputs(tmp_path):
    a_dir = tmp_path / "a dir é"
    a_dir.mkdir()
    latin1 = tmp_path / "latin1.csv"
    latin1.write_bytes(b"sample_id,qc_type\n\xff\xfe,trip_blank\n")
    return a_dir, latin1


@pytest.mark.parametrize("argv", [
    ["envmon", "generate-qc-summary", "--results"],
    ["envmon", "build-gwe-event", "--event-date", "2025-01-01",
     "--water-levels"],
])
def test_unreadable_csv_input_is_a_clean_error(tmp_path, argv):
    for bad in _bad_inputs(tmp_path):
        result = CliRunner().invoke(
            autogis, argv + [str(bad), "--out", str(tmp_path / "o.out")])
        assert result.exit_code == 1, result.output
        assert result.exception is None or isinstance(result.exception,
                                                      SystemExit)
        assert "cannot read" in result.output and str(bad) in result.output


def test_generate_qc_summary_rejects_a_directory_out(tmp_path):
    results = tmp_path / "r.csv"
    results.write_text("sample_id,qc_type\n", encoding="utf-8")
    result = CliRunner().invoke(autogis, [
        "envmon", "generate-qc-summary", "--results", str(results),
        "--out", str(tmp_path)])
    assert result.exit_code == 2, result.output
    assert result.exception is None or isinstance(result.exception,
                                                  SystemExit)
