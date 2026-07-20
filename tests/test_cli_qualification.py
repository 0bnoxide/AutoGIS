from click.testing import CliRunner

from autogis.adapters import cli, qualification
from autogis.adapters.guard import RuntimeUnavailable
from autogis.core.qualify import Check, QualificationReport, write_report_files


def test_qualify_cli_reports_precondition_as_exit_2(tmp_path, monkeypatch):
    def unavailable(_name):
        raise RuntimeUnavailable("arcpy unavailable")

    monkeypatch.setattr(cli, "require_runtime", unavailable)
    result = CliRunner().invoke(
        cli.autogis, ["envmon", "qualify", "--out", str(tmp_path)])

    assert result.exit_code == 2
    assert "Precondition failed" in result.output
    assert (tmp_path / "run_history.csv").exists()


def test_qualify_cli_writes_reports_and_passes_self_test(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "require_runtime", lambda _name: None)

    def run(out_dir, *, self_test=False):
        assert self_test is True
        report = QualificationReport({}, (
            Check("canary.parameter", "fail"),
            Check("canary.scratch-gdb", "fail"),
        ))
        return report, write_report_files(report, out_dir), 0

    monkeypatch.setattr(qualification, "run_qualification", run)
    result = CliRunner().invoke(cli.autogis, [
        "envmon", "qualify", "--out", str(tmp_path), "--self-test",
    ])

    assert result.exit_code == 0, result.output
    assert "Summary: 0 pass, 2 fail, 0 skip" in result.output
    assert "Self-test: PASS" in result.output
    assert (tmp_path / "qualification.json").exists()
