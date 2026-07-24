from __future__ import annotations

import dataclasses

from autogis.core.common.qa import QACollector
from autogis.core.envmon.canonical_read import (
    canonical_records, canonical_result_rows,
)


@dataclasses.dataclass
class _Rec:
    # Minimal stand-in for AnalyticalResultRecord: the group-key fields plus
    # the two discriminators the policy reads. asdict() must expose these names.
    SiteID: str = "S1"
    Matrix: str = "GW"
    LocationID: str = "MW-1"
    SampleID: str = "MW-1-0626"
    SampleDate: str = "2026-06-26"
    AnalyteCanonicalName: str = "Arsenic"
    DepthIntervalText: str = ""
    ResultFraction: str = ""
    QCType: str = ""
    ResultNumeric: float = 1.0


def _row(**ov) -> dict:
    d = {"LocationID": "MW-1", "SampleID": "MW-1-0626",
         "SampleDate": "2026-06-26", "AnalyteCanonicalName": "Arsenic",
         "DepthIntervalText": "", "ResultFraction": "", "QCType": "",
         "NumericValue": 1.0}
    d.update(ov)
    return d


def test_qc_rows_excluded():
    qa = QACollector()
    rows = [_row(), _row(QCType="TRIP_BLANK", NumericValue=0.0)]
    out = canonical_result_rows(rows, qa)
    assert len(out) == 1 and out[0]["QCType"] == ""


def test_total_dissolved_pair_resolves_to_total():
    qa = QACollector()
    rows = [_row(ResultFraction="Total", NumericValue=2.0),
            _row(ResultFraction="Dissolved", NumericValue=1.5)]
    out = canonical_result_rows(rows, qa)
    assert len(out) == 1 and out[0]["ResultFraction"] == "Total"
    assert any(r.category == "fraction_resolved" for r in qa.records)


def test_single_fraction_untouched_even_if_unpreferred():
    qa = QACollector()
    rows = [_row(ResultFraction="Dissolved")]
    assert canonical_result_rows(rows, qa) == rows
    assert not qa.records


def test_unpreferred_multi_fraction_falls_back_deterministically():
    qa = QACollector()
    rows = [_row(ResultFraction="Suspended"),
            _row(ResultFraction="Extractable")]
    out = canonical_result_rows(rows, qa)
    assert len(out) == 1
    assert out[0]["ResultFraction"] == "Extractable"   # sorted()[0]


def test_legacy_rows_pass_through_unchanged():
    # Pre-2.2 rows (both discriminators "") — including rows where the keys
    # are absent entirely — must pass through untouched: no behavior change
    # until Step 2 populates real fractions.
    qa = QACollector()
    legacy = {"LocationID": "MW-2", "SampleID": "S", "SampleDate": "d",
              "AnalyteCanonicalName": "Lead", "DepthIntervalText": ""}
    rows = [_row(), legacy]
    assert canonical_result_rows(rows, qa) == rows
    assert not qa.records


def test_groups_are_independent():
    # A Total/Dissolved pair on one analyte must not affect another
    # analyte's single row in the same sample.
    qa = QACollector()
    rows = [_row(ResultFraction="Total"), _row(ResultFraction="Dissolved"),
            _row(AnalyteCanonicalName="Lead")]
    out = canonical_result_rows(rows, qa)
    assert len(out) == 2


def test_different_sites_not_merged_across_fractions():
    # The reusable helper must NOT collapse two same-location/analyte rows
    # from different SITES into one group — otherwise differing fractions
    # resolve to one and the other is silently dropped (ADR-0075 P1). No
    # caller pre-filter is assumed here.
    qa = QACollector()
    rows = [_row(SiteID="S1", ResultFraction="Total"),
            _row(SiteID="S2", ResultFraction="Dissolved")]
    out = canonical_result_rows(rows, qa)
    assert len(out) == 2
    assert not any(r.category == "fraction_resolved" for r in qa.records)


def test_different_matrices_not_merged_across_fractions():
    # Same guard on the Matrix dimension.
    qa = QACollector()
    rows = [_row(Matrix="GW", ResultFraction="Total"),
            _row(Matrix="SOIL", ResultFraction="Dissolved")]
    out = canonical_result_rows(rows, qa)
    assert len(out) == 2
    assert not any(r.category == "fraction_resolved" for r in qa.records)


def test_canonical_records_returns_same_objects_order_preserved():
    # Record-aware adapter: returns the SAME record instances (not copies),
    # order preserved — consumers rely on identity / dataclasses.replace.
    qa = QACollector()
    a = _Rec(AnalyteCanonicalName="Arsenic")
    b = _Rec(AnalyteCanonicalName="Lead")
    out = canonical_records([a, b], qa)
    assert out[0] is a and out[1] is b
    assert not qa.records


def test_canonical_records_drops_qc():
    qa = QACollector()
    real = _Rec()
    qc = _Rec(QCType="TRIP_BLANK")
    out = canonical_records([real, qc], qa)
    assert out == [real]
    assert any(r.category == "qc_rows_excluded" for r in qa.records)


def test_canonical_records_resolves_fraction_keeps_preferred_record():
    qa = QACollector()
    total = _Rec(ResultFraction="Total", ResultNumeric=2.0)
    diss = _Rec(ResultFraction="Dissolved", ResultNumeric=1.5)
    out = canonical_records([total, diss], qa)
    assert out == [total]                      # Total preferred, same object
    assert any(r.category == "fraction_resolved" for r in qa.records)


def test_canonical_records_legacy_passthrough():
    qa = QACollector()
    recs = [_Rec(), _Rec(AnalyteCanonicalName="Lead")]
    out = canonical_records(recs, qa)
    assert out == recs
    assert not qa.records


def _rerun_row(mdk, reportable, value):
    return {"SiteID": "s", "Matrix": "SOIL", "LocationID": "MW-1",
            "SampleID": "S1", "SampleDate": "2026-01-02",
            "AnalyteCanonicalName": "Arsenic", "DepthIntervalText": "",
            "ResultFraction": "Total", "QCType": "",
            "MethodDilutionKey": mdk, "IsReportable": reportable,
            "ResultNumeric": value}


def test_isreportable_resolves_rerun_groups():
    qa = QACollector()
    rows = [_rerun_row("", 1, 2.0), _rerun_row("5|DILUTION", 0, 2.2)]
    out = canonical_result_rows(rows, qa)
    assert len(out) == 1
    assert out[0]["ResultNumeric"] == 2.0
    assert any(r.category == "rerun_resolved" for r in qa.records)


def test_null_isreportable_reruns_unchanged():
    # pre-Step-3 imports: flag NULL everywhere -> both rows pass (pinned
    # legacy behavior; do NOT guess among reruns without the flag)
    qa = QACollector()
    rows = [_rerun_row("", None, 2.0), _rerun_row("5|DILUTION", None, 2.2)]
    out = canonical_result_rows(rows, qa)
    assert len(out) == 2


def test_single_run_groups_untouched_by_reportable_zero():
    qa = QACollector()
    rows = [_rerun_row("", 0, 2.0)]        # one run, flagged not-reportable
    out = canonical_result_rows(rows, qa)
    assert len(out) == 1                   # never drop a group's only run


def test_conflicting_source_sheets_fail_loud_and_are_excluded():
    rows = [
        _row(SourceSheet="GW Quality", SourceCell="C9", ResultNumeric=1.0),
        _row(SourceSheet="GW Quality (2)", SourceCell="C9", ResultNumeric=2.0),
    ]
    for ordered in (rows, list(reversed(rows))):
        qa = QACollector()
        assert canonical_result_rows(ordered, qa) == []
        assert any(r.category == "source_sheet_conflict"
                   and r.severity == "ERROR" for r in qa.records)


def test_identical_source_sheet_duplicates_keep_first_with_info():
    qa = QACollector()
    first = _row(
        ImportBatchID="B1", SourceSheet="GW Quality", SourceCell="C9",
        ResultNumeric=1.0)
    duplicate = {
        **first, "ImportBatchID": "B2", "SourceSheet": "Archive",
        "SourceCell": "D12",
    }
    assert canonical_result_rows([first, duplicate], qa) == [first]
    assert any(r.category == "source_sheet_duplicate"
               and r.severity == "INFO" for r in qa.records)


def test_pivot_no_longer_drops_or_double_counts_fractions():
    from autogis.core.envmon.build_current_event import build_wide_rows
    qa = QACollector()
    pair = [
        _row(ResultFraction="Total", NumericValue=2.0, IsDetected=1,
             DisplayText="2.0"),
        _row(ResultFraction="Dissolved", NumericValue=1.5, IsDetected=1,
             DisplayText="1.5"),
    ]
    canonical = canonical_result_rows(pair, qa)
    wide = build_wide_rows(canonical, ["Arsenic"], qa)
    assert len(wide) == 1
    assert wide[0]["results"]["Arsenic"]["DisplayText"] == "2.0"   # Total won
    # and the old silent-overwrite warning did NOT fire
    assert not any(r.category == "multiple_results_after_rules"
                   for r in qa.records)
