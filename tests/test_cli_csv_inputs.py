"""CSV inputs that pass ``click.Path(exists=True)`` but cannot be read -- a
directory, a non-UTF-8 file -- are a clean CLI error, not a traceback (#573).
"""
import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis


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


@pytest.mark.parametrize("argv", [
    ["envmon", "drone-checkpoint-qa", "--checkpoints"],
    ["envmon", "rtk-control-check", "--control-points"],
])
def test_checkpoint_csv_bad_input_is_a_clean_error(tmp_path, argv):
    """#595: unreadable files and malformed rows exit 1 with a message."""
    wrong_columns = tmp_path / "wrong.csv"
    wrong_columns.write_text("a,b\n1,2\n", encoding="utf-8")
    short_row = tmp_path / "short.csv"
    short_row.write_text(
        "gcp_id,control_id,expected_x,published_x\nG1\n", encoding="utf-8")
    for bad, expected in [*((b, "cannot read") for b in _bad_inputs(tmp_path)),
                          (wrong_columns, "line 2"), (short_row, "line 2")]:
        result = CliRunner().invoke(autogis, argv + [str(bad)])
        assert result.exit_code == 1, result.output
        assert result.exception is None or isinstance(result.exception,
                                                      SystemExit)
        assert expected in result.output and str(bad) in result.output
