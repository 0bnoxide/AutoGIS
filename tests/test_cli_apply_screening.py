"""CLI tests for apply-screening."""
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
    with output_csv.open() as fh:
        rows = list(csv.DictReader(fh))
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
    with output_csv.open() as fh:
        rows = list(csv.DictReader(fh))
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
    with output_csv.open() as fh:
        rows = list(csv.DictReader(fh))
    # No matching screening entry — record passed through unchanged. The input's
    # blank ExceedsScreeningLevel is a tri-state Optional[int] meaning "no
    # screening level / unknown", so it round-trips as None -> "" (not 0, which
    # would wrongly assert "does not exceed" for an unscreened analyte).
    assert rows[0]["ExceedsScreeningLevel"] == ""


def test_shipped_canonical_screening_file_flags_exceedance(tmp_path):
    """#646: the shipped screening_levels.yaml matched nothing -> silent PASS."""
    results = tmp_path / "r.csv"
    _write_csv(results, [_result_row(num="100000")])
    shipped = (Path(__file__).resolve().parents[1] / "autogis" / "config"
               / "screening_levels" / "screening_levels.yaml")
    out = tmp_path / "o.csv"
    r = CliRunner().invoke(autogis, ["envmon", "apply-screening", "--results-csv",
                                     str(results), "--screening", str(shipped),
                                     "--output", str(out)])
    assert r.exit_code == 0, r.output
    with open(out, encoding="utf-8") as fh:
        row = next(csv.DictReader(fh))
    assert row["ExceedsScreeningLevel"] == "1" and row["ScreeningLevel"] in ("5", "5.0")
