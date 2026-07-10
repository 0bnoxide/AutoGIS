from __future__ import annotations

from autogis.core.common.qa import QACollector
from autogis.core.envmon.canonical_read import canonical_result_rows


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
