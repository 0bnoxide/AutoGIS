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


def test_batch_import_workbooks_bad_inputs_are_clean_errors(tmp_path):
    """#601: a bad --manifest / --analytes / --screening was a traceback."""
    a_dir, latin1 = _bad_inputs(tmp_path)
    wrong_cols = tmp_path / "wrong.csv"
    wrong_cols.write_text("foo,bar\n1,2\n", encoding="utf-8")
    broken_yaml = tmp_path / "broken.yaml"
    broken_yaml.write_text("a: [\n", encoding="utf-8")
    manifest = tmp_path / "m.csv"
    manifest.write_text("workbook_path,profile_path,site_id\n",
                        encoding="utf-8")
    cases = [(["--manifest", str(p)], p) for p in (a_dir, latin1, wrong_cols)]
    cases += [(["--manifest", str(manifest), opt, str(p)], p)
              for opt in ("--analytes", "--screening")
              for p in (a_dir, latin1, broken_yaml)]
    for args, bad in cases:
        result = CliRunner().invoke(autogis, [
            "envmon", "batch-import-workbooks", *args,
            "--output-dir", str(tmp_path / "out")])
        assert result.exit_code == 1, (args, result.output)
        assert result.exception is None or isinstance(result.exception,
                                                      SystemExit), args
        assert result.output.startswith("Error:") and str(bad) in result.output


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
    after_blank = tmp_path / "blank.csv"  # bad row on file line 3
    after_blank.write_text("a,b\n\n1,2\n", encoding="utf-8")
    huge_field = tmp_path / "huge.csv"  # over csv's 131072-char field limit
    huge_field.write_text('a\n"' + "x" * 200_000 + '"\n', encoding="utf-8")
    for bad, expected in [*((b, "cannot read") for b in _bad_inputs(tmp_path)),
                          (huge_field, "cannot read"),
                          (wrong_columns, "line 2"), (short_row, "line 2"),
                          (after_blank, "line 3")]:
        result = CliRunner().invoke(autogis, argv + [str(bad)])
        assert result.exit_code == 1, result.output
        assert result.exception is None or isinstance(result.exception,
                                                      SystemExit)
        assert expected in result.output and str(bad) in result.output
