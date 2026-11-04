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
