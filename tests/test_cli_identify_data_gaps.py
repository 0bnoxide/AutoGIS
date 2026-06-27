"""CLI tests for envmon identify-data-gaps (Tool 4.10)."""
import csv
import dataclasses
from datetime import date
from pathlib import Path

import yaml
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


def _r(loc, analyte, d=date(2026, 4, 1)):
    return AnalyticalResultRecord(
        ImportBatchID="B", SiteID="H281", Matrix="GW", LocationID=loc,
        SampleID=f"{loc}-{analyte}", ParentSampleID="", SampleDate=d,
        DepthTop_ft=None, DepthBottom_ft=None, DepthIntervalText="",
        AnalyticalGroup="VOC", MethodGroup="EPA8260", AnalyteName=analyte,
        AnalyteCanonicalName=analyte, AnalyteAbbreviation=analyte[:3],
        ResultRawText="1.0", ResultNumeric=1.0, ReportingLimit=None,
        DetectionLimit=None, Units="ug/L", Qualifier="", IsNonDetect=0,
        IsDetected=1, IsEstimated=0, IsDiluted=0, IsNotAnalyzed=0,
        IsNotSampled=0, IsNotMeasured=0, ScreeningLevel=5.0,
        ScreeningLevelSource="RBSL", ExceedsScreeningLevel=0, DisplayText="1.0",
        DisplayColorClass="OK", SourceWorkbook="t.xlsx", SourceSheet="S1",
        SourceRow=1, SourceColumn="A", SourceCell="A1")


SCHEDULE = {
    "site_id": "H281", "event_label": "2026Q2",
    "wells": ["MW-1", "MW-2"],
    "required_analytes": ["Benzene", "Toluene"],
}


def test_help_lists_options():
    r = CliRunner().invoke(autogis, ["envmon", "identify-data-gaps", "--help"])
    assert r.exit_code == 0
    for opt in ("--results-csv", "--schedule", "--output", "--event-date",
                "--event-window-days", "--dry-wells"):
        assert opt in r.output


def test_happy_path_no_gaps(tmp_path):
    results = [_r("MW-1", a) for a in ("Benzene", "Toluene")]
    results += [_r("MW-2", a) for a in ("Benzene", "Toluene")]
    in_csv = tmp_path / "results.csv"
    sched_yaml = tmp_path / "schedule.yaml"
    out_csv = tmp_path / "gaps.csv"
    _write_results_csv(in_csv, results)
    sched_yaml.write_text(yaml.dump(SCHEDULE), encoding="utf-8")

    r = CliRunner().invoke(autogis, [
        "envmon", "identify-data-gaps",
        "--results-csv", str(in_csv),
        "--schedule", str(sched_yaml),
        "--output", str(out_csv),
        "--event-date", "2026-04-01",
    ])
    assert r.exit_code == 0, r.output
    assert out_csv.exists()
    rows = list(csv.DictReader(out_csv.open(encoding="utf-8")))
    assert all(r["GapType"] not in ("MISSING_WELL", "MISSED_ANALYTE") for r in rows)


def test_missing_well_exits_nonzero(tmp_path):
    # Only MW-1 has results; MW-2 is missing
    results = [_r("MW-1", a) for a in ("Benzene", "Toluene")]
    in_csv = tmp_path / "results.csv"
    sched_yaml = tmp_path / "schedule.yaml"
    out_csv = tmp_path / "gaps.csv"
    _write_results_csv(in_csv, results)
    sched_yaml.write_text(yaml.dump(SCHEDULE), encoding="utf-8")

    r = CliRunner().invoke(autogis, [
        "envmon", "identify-data-gaps",
        "--results-csv", str(in_csv),
        "--schedule", str(sched_yaml),
        "--output", str(out_csv),
        "--event-date", "2026-04-01",
        "--fail-on", "error",
    ])
    assert r.exit_code == 1


def test_dry_wells_csv(tmp_path):
    # MW-2 is listed as dry; should appear as DRY_OR_INACCESSIBLE, not MISSING_WELL
    results = [_r("MW-1", a) for a in ("Benzene", "Toluene")]
    in_csv = tmp_path / "results.csv"
    sched_yaml = tmp_path / "schedule.yaml"
    dry_csv = tmp_path / "dry.csv"
    out_csv = tmp_path / "gaps.csv"
    _write_results_csv(in_csv, results)
    sched_yaml.write_text(yaml.dump(SCHEDULE), encoding="utf-8")
    dry_csv.write_text("location_id,reason\nMW-2,dry\n", encoding="utf-8")

    r = CliRunner().invoke(autogis, [
        "envmon", "identify-data-gaps",
        "--results-csv", str(in_csv),
        "--schedule", str(sched_yaml),
        "--output", str(out_csv),
        "--event-date", "2026-04-01",
        "--dry-wells", str(dry_csv),
    ])
    # DRY_OR_INACCESSIBLE is INFO; --fail-on error should exit 0
    assert r.exit_code == 0, r.output
    rows = list(csv.DictReader(out_csv.open(encoding="utf-8")))
    assert any(row["GapType"] == "DRY_OR_INACCESSIBLE" for row in rows)
    assert not any(row["GapType"] == "MISSING_WELL" for row in rows)
