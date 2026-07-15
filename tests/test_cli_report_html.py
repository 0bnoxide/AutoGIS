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
