from pathlib import Path
from click.testing import CliRunner
from autogis.adapters.cli import autogis


def test_event_report_format_html(tmp_path):
    r = tmp_path / "results.csv"
    r.write_text("LocationID,AnalyteCanonicalName,DisplayText,ScreeningLevel,"
                 "ExceedsScreeningLevel,DisplayColorClass\nMW-1,Benzene,5.5,5,1,EXCEED\n",
                 encoding="utf-8")
    out = tmp_path / "report.html"
    res = CliRunner().invoke(autogis, [
        "envmon", "generate-event-report", "--site", "S", "--event", "E",
        "--results-csv", str(r), "--output", str(out), "--format", "html",
    ])
    assert res.exit_code == 0, res.output
    assert out.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_well_inspection_format_html(tmp_path):
    w = tmp_path / "wells.csv"
    w.write_text("WellID,Owner\nMW-1,ACME\n", encoding="utf-8")
    out = tmp_path / "out"
    res = CliRunner().invoke(autogis, [
        "envmon", "well-inspection-report", "--wells-csv", str(w),
        "--site", "S", "--output-dir", str(out), "--format", "html",
    ])
    assert res.exit_code == 0, res.output
    assert (out / "MW-1.html").exists() and (out / "SiteSummary.html").exists()


def test_well_inspection_missing_pillow_clean_error(tmp_path, monkeypatch):
    # Missing Pillow fail-fast (ImportError) surfaces as a clean CLI error,
    # not a raw traceback (#501).
    import autogis.adapters.cli as cli_mod

    def boom(*args, **kwargs):
        raise ImportError('Pillow is required to embed photos. Install with: '
                          'pip install "autogis[report]"')

    monkeypatch.setattr(
        "autogis.core.envmon.well_inspection_report."
        "build_well_inspection_reports", boom)
    w = tmp_path / "wells.csv"
    w.write_text("WellID,Owner\nMW-1,ACME\n", encoding="utf-8")
    res = CliRunner().invoke(autogis, [
        "envmon", "well-inspection-report", "--wells-csv", str(w),
        "--site", "S", "--output-dir", str(tmp_path / "out"), "--format", "html",
    ])
    assert res.exit_code != 0
    assert "Pillow is required" in res.output
    assert "Traceback" not in res.output
