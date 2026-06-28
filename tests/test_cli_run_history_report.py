"""CLI tests for run-history-report (Tool 10.1)."""
import csv
import pytest
from click.testing import CliRunner
from pathlib import Path
from autogis.adapters.cli import autogis


def _write_results_csv(path, rows):
    if not rows:
        fieldnames = [
            "ImportBatchID","SiteID","Matrix","LocationID","SampleID","ParentSampleID",
            "SampleDate","DepthTop_ft","DepthBottom_ft","DepthIntervalText",
            "AnalyticalGroup","MethodGroup","AnalyteName","AnalyteCanonicalName",
            "AnalyteAbbreviation","ResultRawText","ResultNumeric","ReportingLimit",
            "DetectionLimit","Units","Qualifier","IsNonDetect","IsDetected",
            "IsEstimated","IsDiluted","IsNotAnalyzed","IsNotSampled","IsNotMeasured",
            "ScreeningLevel","ScreeningLevelSource","ExceedsScreeningLevel",
            "DisplayText","DisplayColorClass","SourceWorkbook","SourceSheet",
            "SourceRow","SourceColumn","SourceCell",
        ]
        with open(path, "w", newline="") as fh:
            csv.DictWriter(fh, fieldnames=fieldnames).writeheader()
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def _result_row(loc="MW-1", analyte="Benzene", num="5.0", date_str="2026-01-01"):
    return {
        "ImportBatchID": "B", "SiteID": "S", "Matrix": "GW",
        "LocationID": loc, "SampleID": "S1", "ParentSampleID": "",
        "SampleDate": date_str, "DepthTop_ft": "", "DepthBottom_ft": "",
        "DepthIntervalText": "", "AnalyticalGroup": "VOC", "MethodGroup": "EPA8260",
        "AnalyteName": analyte, "AnalyteCanonicalName": analyte,
        "AnalyteAbbreviation": analyte[:3], "ResultRawText": num,
        "ResultNumeric": num, "ReportingLimit": "", "DetectionLimit": "",
        "Units": "ug/L", "Qualifier": "", "IsNonDetect": "0", "IsDetected": "1",
        "IsEstimated": "0", "IsDiluted": "0", "IsNotAnalyzed": "0",
        "IsNotSampled": "0", "IsNotMeasured": "0", "ScreeningLevel": "",
        "ScreeningLevelSource": "", "ExceedsScreeningLevel": "",
        "DisplayText": num, "DisplayColorClass": "",
        "SourceWorkbook": "t.xlsx", "SourceSheet": "S1",
        "SourceRow": "1", "SourceColumn": "A", "SourceCell": "A1",
    }


def test_run_history_report_basic(tmp_path):
    runner = CliRunner()
    results_csv = tmp_path / "results.csv"
    output_csv = tmp_path / "history.csv"
    _write_results_csv(results_csv, [
        _result_row("MW-1", "Benzene", "5.0", "2026-01-01"),
        _result_row("MW-1", "Benzene", "10.0", "2026-04-01"),
    ])
    result = runner.invoke(autogis, [
        "envmon", "run-history-report",
        "--results-csv", str(results_csv),
        "--output", str(output_csv),
    ])
    assert result.exit_code == 0, result.output
    assert output_csv.exists()
    rows = list(csv.DictReader(output_csv.open()))
    assert len(rows) == 1
    assert rows[0]["TrendVsPrevious"] == "INCREASE"


def test_run_history_report_empty(tmp_path):
    runner = CliRunner()
    results_csv = tmp_path / "results.csv"
    output_csv = tmp_path / "history.csv"
    _write_results_csv(results_csv, [])
    result = runner.invoke(autogis, [
        "envmon", "run-history-report",
        "--results-csv", str(results_csv),
        "--output", str(output_csv),
    ])
    assert result.exit_code == 0, result.output
    rows = list(csv.DictReader(output_csv.open()))
    assert len(rows) == 0
