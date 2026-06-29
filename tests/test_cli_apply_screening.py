"""CLI tests for apply-screening (Tool 3.5)."""
import csv
import yaml
from click.testing import CliRunner
from pathlib import Path
from autogis.adapters.cli import autogis

SCREENING_YAML = {
    "Benzene": {"GW": {"unit": "ug/L", "level": 5.0, "source": "RBSL"}}
}


def _result_row(analyte="Benzene", num="10.0", exceed=""):
    return {
        "ImportBatchID": "B", "SiteID": "S", "Matrix": "GW",
        "LocationID": "MW-1", "SampleID": "S1", "ParentSampleID": "",
        "SampleDate": "2026-04-01", "DepthTop_ft": "", "DepthBottom_ft": "",
        "DepthIntervalText": "", "AnalyticalGroup": "VOC", "MethodGroup": "EPA8260",
        "AnalyteName": analyte, "AnalyteCanonicalName": analyte,
        "AnalyteAbbreviation": analyte[:3], "ResultRawText": num,
        "ResultNumeric": num, "ReportingLimit": "", "DetectionLimit": "",
        "Units": "ug/L", "Qualifier": "", "IsNonDetect": "0", "IsDetected": "1",
        "IsEstimated": "0", "IsDiluted": "0", "IsNotAnalyzed": "0",
        "IsNotSampled": "0", "IsNotMeasured": "0", "ScreeningLevel": "",
        "ScreeningLevelSource": "", "ExceedsScreeningLevel": exceed,
        "DisplayText": num, "DisplayColorClass": "",
        "SourceWorkbook": "t.xlsx", "SourceSheet": "S1",
        "SourceRow": "1", "SourceColumn": "A", "SourceCell": "A1",
    }


def _write_csv(path, rows):
    fieldnames = list(rows[0].keys()) if rows else []
    if not fieldnames:
        return
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def test_apply_screening_basic(tmp_path):
    runner = CliRunner()
    results_csv = tmp_path / "results.csv"
    screening_yaml = tmp_path / "screening.yaml"
    output_csv = tmp_path / "updated.csv"
    _write_csv(results_csv, [_result_row("Benzene", "10.0")])
    screening_yaml.write_text(yaml.dump(SCREENING_YAML), encoding="utf-8")
    result = runner.invoke(autogis, [
        "envmon", "apply-screening",
        "--results-csv", str(results_csv),
        "--screening", str(screening_yaml),
        "--output", str(output_csv),
    ])
    assert result.exit_code == 0, result.output
    rows = list(csv.DictReader(output_csv.open()))
    assert len(rows) == 1
    assert rows[0]["ExceedsScreeningLevel"] == "1"
    assert rows[0]["DisplayColorClass"] == "EXCEED"


def test_apply_screening_no_exceedance(tmp_path):
    runner = CliRunner()
    results_csv = tmp_path / "results.csv"
    screening_yaml = tmp_path / "screening.yaml"
    output_csv = tmp_path / "updated.csv"
    _write_csv(results_csv, [_result_row("Benzene", "3.0")])
    screening_yaml.write_text(yaml.dump(SCREENING_YAML), encoding="utf-8")
    result = runner.invoke(autogis, [
        "envmon", "apply-screening",
        "--results-csv", str(results_csv),
        "--screening", str(screening_yaml),
        "--output", str(output_csv),
    ])
    assert result.exit_code == 0, result.output
    rows = list(csv.DictReader(output_csv.open()))
    assert rows[0]["ExceedsScreeningLevel"] == "0"
    assert rows[0]["DisplayColorClass"] == "OK"


def test_apply_screening_no_match_passthrough(tmp_path):
    runner = CliRunner()
    results_csv = tmp_path / "results.csv"
    screening_yaml = tmp_path / "screening.yaml"
    output_csv = tmp_path / "updated.csv"
    _write_csv(results_csv, [_result_row("Toluene", "99.0")])
    screening_yaml.write_text(yaml.dump(SCREENING_YAML), encoding="utf-8")
    result = runner.invoke(autogis, [
        "envmon", "apply-screening",
        "--results-csv", str(results_csv),
        "--screening", str(screening_yaml),
        "--output", str(output_csv),
    ])
    assert result.exit_code == 0, result.output
    rows = list(csv.DictReader(output_csv.open()))
    # No matching screening entry — record passed through unchanged. The input's
    # blank ExceedsScreeningLevel is a tri-state Optional[int] meaning "no
    # screening level / unknown", so it round-trips as None -> "" (not 0, which
    # would wrongly assert "does not exceed" for an unscreened analyte).
    assert rows[0]["ExceedsScreeningLevel"] == ""
