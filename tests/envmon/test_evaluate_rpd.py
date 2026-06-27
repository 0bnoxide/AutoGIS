from autogis.core.envmon.evaluate_rpd import (
    EvaluateRPDResult, evaluate_rpd_records, rpd_to_qa,
)
from autogis.core.envmon.gdb_schema import RPDRecord
from click.testing import CliRunner
from autogis.adapters.cli import autogis

_RECORD_PASS = RPDRecord(
    ImportBatchID="B1", SiteID="TEST", EventDate=None,
    ParentLocationID="MW-01", DuplicateLocationID="MW-01D",
    AnalyteName="Benzene",
    ParentResultRaw="5.0", DuplicateResultRaw="4.8",
    ParentResultNumeric=5.0, DuplicateResultNumeric=4.8,
    RPDValue=4.08, RL=None, FiveTimesRL=None,
    RPDStatus="CALCULATED", CalculationError="",
    SourceWorkbook="test.xlsx", SourceSheet="RPD", SourceRow=5)

_RECORD_FAIL = RPDRecord(
    ImportBatchID="B1", SiteID="TEST", EventDate=None,
    ParentLocationID="MW-02", DuplicateLocationID="MW-02D",
    AnalyteName="Benzene",
    ParentResultRaw="5.0", DuplicateResultRaw="9.0",
    ParentResultNumeric=5.0, DuplicateResultNumeric=9.0,
    RPDValue=57.1, RL=None, FiveTimesRL=None,
    RPDStatus="CALCULATED", CalculationError="",
    SourceWorkbook="test.xlsx", SourceSheet="RPD", SourceRow=6)


def test_passing_rpd_no_exceedance():
    result = evaluate_rpd_records([_RECORD_PASS], rpd_threshold_pct=30.0)
    assert result.passed == 1
    assert result.failed == 0


def test_failing_rpd_flags_exceedance():
    result = evaluate_rpd_records([_RECORD_FAIL], rpd_threshold_pct=30.0)
    assert result.failed == 1
    assert result.passed == 0


def test_nc_nondetect_excluded_from_pass_fail():
    import dataclasses
    rec = dataclasses.replace(_RECORD_PASS, RPDStatus="NC_NONDETECT", RPDValue=None)
    result = evaluate_rpd_records([rec], rpd_threshold_pct=30.0)
    assert result.not_calculable == 1
    assert result.passed == 0 and result.failed == 0


def test_rpd_to_qa_produces_error_for_exceedance():
    result = evaluate_rpd_records([_RECORD_FAIL], rpd_threshold_pct=30.0)
    qa = rpd_to_qa(result)
    assert any(r.category == "rpd_exceedance" for r in qa.records)


def test_rpd_to_qa_no_error_when_all_pass():
    result = evaluate_rpd_records([_RECORD_PASS], rpd_threshold_pct=30.0)
    qa = rpd_to_qa(result)
    assert qa.counts_by_severity().get("ERROR", 0) == 0


def test_evaluate_rpd_result_total():
    result = evaluate_rpd_records([_RECORD_PASS, _RECORD_FAIL], rpd_threshold_pct=30.0)
    assert result.total == 2


def test_evaluate_rpd_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "evaluate-rpd" in result.output
