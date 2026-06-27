"""CLI tests for envmon compare-events (Tool 4.7)."""
import csv
import dataclasses
from datetime import date
from pathlib import Path

import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.envmon.gdb_schema import AnalyticalResultRecord


def _write_results_csv(path: Path, records):
    fields = [f.name for f in dataclasses.fields(AnalyticalResultRecord)]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for rec in records:
            w.writerow(dataclasses.asdict(rec))


def _r(loc, analyte, d, *, raw="1.0", num=1.0, detected=1, nondetect=0, exceed=0):
    return AnalyticalResultRecord(
        ImportBatchID="B", SiteID="S", Matrix="GW", LocationID=loc,
        SampleID=f"{loc}-{analyte}-{d}", ParentSampleID="", SampleDate=d,
        DepthTop_ft=None, DepthBottom_ft=None, DepthIntervalText="",
        AnalyticalGroup="VOC", MethodGroup="EPA8260", AnalyteName=analyte,
        AnalyteCanonicalName=analyte, AnalyteAbbreviation=analyte[:3],
        ResultRawText=raw, ResultNumeric=num, ReportingLimit=None,
        DetectionLimit=None, Units="ug/L", Qualifier="",
        IsNonDetect=nondetect, IsDetected=detected, IsEstimated=0, IsDiluted=0,
        IsNotAnalyzed=0, IsNotSampled=0, IsNotMeasured=0, ScreeningLevel=5.0,
        ScreeningLevelSource="RBSL", ExceedsScreeningLevel=exceed,
        DisplayText=raw, DisplayColorClass="OK", SourceWorkbook="t.xlsx",
        SourceSheet="S1", SourceRow=1, SourceColumn="A", SourceCell="A1")


def test_help_lists_options():
    r = CliRunner().invoke(autogis, ["envmon", "compare-events", "--help"])
    assert r.exit_code == 0
    for opt in ("--results-csv", "--output", "--current-event-date",
                "--stable-threshold", "--report", "--fail-on"):
        assert opt in r.output


def test_happy_path(tmp_path):
    recs = [
        _r("MW-1", "Benzene", date(2026, 1, 1), raw="10", num=10.0),
        _r("MW-1", "Benzene", date(2026, 4, 1), raw="20", num=20.0),
        _r("MW-2", "Toluene", date(2026, 1, 1), raw="5", num=5.0),
        _r("MW-2", "Toluene", date(2026, 4, 1), raw="3", num=3.0),
    ]
    in_csv = tmp_path / "results.csv"
    out_csv = tmp_path / "comparisons.csv"
    _write_results_csv(in_csv, recs)

    r = CliRunner().invoke(autogis, [
        "envmon", "compare-events",
        "--results-csv", str(in_csv),
        "--output", str(out_csv),
    ])
    assert r.exit_code == 0, r.output
    assert out_csv.exists()
    rows = list(csv.DictReader(out_csv.open(encoding="utf-8")))
    assert len(rows) == 2
    # Verify header has ComparisonRecord fields
    assert "TrendClass" in rows[0]
    assert "PercentChange" in rows[0]


def test_current_event_date_option(tmp_path):
    recs = [
        _r("MW-1", "Benzene", date(2026, 1, 1), raw="10", num=10.0),
        _r("MW-1", "Benzene", date(2026, 4, 1), raw="20", num=20.0),
        _r("MW-2", "Benzene", date(2026, 1, 1), raw="5", num=5.0),  # no Apr record
    ]
    in_csv = tmp_path / "results.csv"
    out_csv = tmp_path / "comparisons.csv"
    _write_results_csv(in_csv, recs)

    r = CliRunner().invoke(autogis, [
        "envmon", "compare-events",
        "--results-csv", str(in_csv),
        "--output", str(out_csv),
        "--current-event-date", "2026-04-01",
    ])
    assert r.exit_code == 0, r.output
    rows = list(csv.DictReader(out_csv.open(encoding="utf-8")))
    # Only MW-1 has an April record
    assert len(rows) == 1
    assert rows[0]["LocationID"] == "MW-1"
