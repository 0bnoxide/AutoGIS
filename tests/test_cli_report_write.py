"""An unwritable ``--report`` is a clean CLI error, not a traceback (#651).

``_render_qa`` writes ``--report`` for every headless QA command, so one
command exercises the shared seam.
"""
import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis


@pytest.mark.parametrize("suffix", [".md", ".csv", ".json"])
@pytest.mark.parametrize("kind", ["directory", "under_a_file"])
def test_unwritable_report_is_clean_error(tmp_path, suffix, kind):
    manifest = tmp_path / "m.csv"
    manifest.write_text("workbook_path,profile_path,site_id\n"
                        "missing.csv,missing.yml,S1\n", encoding="utf-8")
    if kind == "directory":
        report = tmp_path / f"report é{suffix}"
        report.mkdir()
    else:
        blocker = tmp_path / "plain file"
        blocker.write_text("x", encoding="utf-8")
        report = blocker / f"report{suffix}"

    result = CliRunner().invoke(autogis, [
        "envmon", "batch-import-workbooks", "--manifest", str(manifest),
        "--output-dir", str(tmp_path / "out"), "--report", str(report)])

    assert result.exit_code == 1, result.output
    assert not isinstance(result.exception, OSError), result.exception
    assert f"Error: cannot write {report}" in result.output
