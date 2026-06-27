import dataclasses
from datetime import date
import csv as _csv

from autogis.core.common.qa import QACollector, SEV_WARNING, SEV_ERROR, SEV_INFO
from autogis.core.envmon.gdb_schema import SampleRecord, AnalyticalResultRecord, RPDRecord
from autogis.core.envmon.evaluate_rpd_qa import evaluate_duplicate_rpd


def _sample(sample_id, parent_id="", is_dup=0, matrix="GROUNDWATER",
            loc="MW-1", dt=date(2026, 1, 1)):
    return SampleRecord(
        ImportBatchID="B1", SiteID="H281", Matrix=matrix,
        LocationID=loc, SampleID=sample_id, ParentSampleID=parent_id,
        SampleDate=dt, SampleDateRaw=str(dt),
        DepthTop_ft=None, DepthBottom_ft=None, DepthIntervalText="",
        IsDuplicate=is_dup, DuplicateType="FIELD_DUP" if is_dup else "",
        LabSampleID="", SourceWorkbook="edd.csv", SourceSheet="", SourceRow=0)


def _result(sample_id, analyte, numeric, raw="", is_det=1, units="ug/L"):
    return AnalyticalResultRecord(
        ImportBatchID="B1", SiteID="H281", Matrix="GROUNDWATER",
        LocationID="MW-1", SampleID=sample_id, ParentSampleID="",
        SampleDate=date(2026, 1, 1),
        DepthTop_ft=None, DepthBottom_ft=None, DepthIntervalText="",
        AnalyticalGroup="VOC", MethodGroup="", AnalyteName=analyte,
        AnalyteCanonicalName=analyte, AnalyteAbbreviation=analyte[:8],
        ResultRawText=raw or str(numeric),
        ResultNumeric=numeric, ReportingLimit=None, DetectionLimit=None,
        Units=units, Qualifier="",
        IsNonDetect=0, IsDetected=is_det, IsEstimated=0, IsDiluted=0,
        IsNotAnalyzed=0, IsNotSampled=0, IsNotMeasured=0,
        ScreeningLevel=None, ScreeningLevelSource="",
        ExceedsScreeningLevel=None, DisplayText="", DisplayColorClass="",
        SourceWorkbook="edd.csv", SourceSheet="", SourceRow=0,
        SourceColumn="", SourceCell="")


def test_rpd_calculated_for_duplicate_pair():
    samples = [
        _sample("S1", is_dup=0),
        _sample("S1-DUP", parent_id="S1", is_dup=1)]
    results = [
        _result("S1", "Benzene", 10.0),
        _result("S1-DUP", "Benzene", 12.0)]
    qa = QACollector()
    rpd_recs = evaluate_duplicate_rpd(samples, results, "H281", "B1", qa)
    assert len(rpd_recs) == 1
    rec = rpd_recs[0]
    assert rec.RPDStatus == "CALCULATED"
    # RPD = |10-12| / ((10+12)/2) * 100 = 2/11 * 100 ≈ 18.18
    assert abs(rec.RPDValue - 18.18) < 0.1


def test_nondetect_pair_marked_nc():
    samples = [_sample("S2"), _sample("S2-DUP", "S2", 1)]
    results = [
        _result("S2", "Benzene", None, raw="<1.0", is_det=0),
        _result("S2-DUP", "Benzene", None, raw="<1.0", is_det=0)]
    results[0].IsNonDetect = 1; results[0].IsDetected = 0
    results[1].IsNonDetect = 1; results[1].IsDetected = 0
    qa = QACollector()
    recs = evaluate_duplicate_rpd(samples, results, "H281", "B1", qa)
    assert len(recs) == 1
    assert recs[0].RPDStatus == "NC_NONDETECT"


def test_formula_error_row_yields_qa_warning():
    samples = [_sample("S3"), _sample("S3-DUP", "S3", 1)]
    results = [
        _result("S3", "Lead", 5.0),
        _result("S3-DUP", "Lead", None, raw="#VALUE!", is_det=0)]
    results[1].IsNotAnalyzed = 1
    qa = QACollector()
    evaluate_duplicate_rpd(samples, results, "H281", "B1", qa)
    cats = [r.category for r in qa.records]
    assert "rpd_formula_error" in cats


def test_no_duplicates_returns_empty():
    samples = [_sample("S4")]
    results = [_result("S4", "TCE", 2.0)]
    qa = QACollector()
    assert evaluate_duplicate_rpd(samples, results, "H281", "B1", qa) == []


# --- Task 3b: read_records_csv ---
from autogis.core.envmon.evaluate_rpd_qa import read_records_csv


def test_read_records_csv_round_trips_sample_record(tmp_path):
    s = _sample("S99")
    p = tmp_path / "samples.csv"
    fnames = [f.name for f in dataclasses.fields(SampleRecord)]
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = _csv.DictWriter(fh, fieldnames=fnames)
        w.writeheader()
        w.writerow(dataclasses.asdict(s))
    loaded = read_records_csv(p, SampleRecord)
    assert len(loaded) == 1
    assert loaded[0].SampleID == "S99"
    assert loaded[0].IsDuplicate == 0


# --- Task 3b: CLI ---
from click.testing import CliRunner
from autogis.adapters.cli import autogis as _cli


def _write_csv(path, record_class, records):
    fnames = [f.name for f in dataclasses.fields(record_class)]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = _csv.DictWriter(fh, fieldnames=fnames)
        w.writeheader()
        for r in records:
            w.writerow(dataclasses.asdict(r))


def test_evaluate_rpd_qa_cli(tmp_path):
    samples = [_sample("P1"), _sample("P1-DUP", "P1", 1)]
    results = [_result("P1", "Benzene", 10.0), _result("P1-DUP", "Benzene", 12.0)]
    sc = tmp_path / "samples.csv"
    rc = tmp_path / "results.csv"
    _write_csv(sc, SampleRecord, samples)
    _write_csv(rc, AnalyticalResultRecord, results)
    r = CliRunner().invoke(_cli, [
        "envmon", "evaluate-rpd-qa",
        "--samples-csv", str(sc), "--results-csv", str(rc)])
    assert r.exit_code == 0
    assert "CALCULATED" in r.output or "rpd_complete" in r.output
