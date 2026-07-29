"""Regression tests for the report-family input guards (issues #339, #376)."""
import csv

import pytest

from autogis.core.common.qa import QACollector
from autogis.core.envmon.build_exceedance_event import build_exceedance_event
from autogis.core.envmon.compliance_summary import build_compliance_summary
from autogis.core.envmon.max_result_dataset import build_max_result_dataset
from autogis.core.envmon.report_input import (
    normalize_report_rows,
    validate_iso_date,
)

# A row in the CANONICAL vocabulary (what every sibling command emits) --
# this is exactly the input that used to be silently misread.
CANONICAL_ROW = {
    "LocationID": "MW-1", "AnalyteName": "Benzene",
    "SampleID": "MW-1-20260701", "SampleDate": "2026-07-01",
    "ResultNumeric": "50", "Qualifier": "", "Units": "ug/L",
}
REPORT_ROW = {
    "LocationID": "MW-1", "AnalyteName": "Benzene",
    "SampleID": "MW-1-20260701", "SampleDate": "2026-07-01",
    "ResultValue": "50", "ResultQualifier": "", "ReportedUnits": "ug/L",
}


# --------------------------------------------------------------- #339 --
def test_canonical_row_backfills_report_vocabulary():
    out = normalize_report_rows([CANONICAL_ROW])
    assert out[0]["ResultValue"] == "50"
    assert out[0]["ReportedUnits"] == "ug/L"


def test_normalize_does_not_mutate_input():
    row = dict(CANONICAL_ROW)
    normalize_report_rows([row])
    assert "ResultValue" not in row


def test_report_vocabulary_wins_when_both_present():
    row = {**CANONICAL_ROW, "ResultValue": "99"}
    assert normalize_report_rows([row])[0]["ResultValue"] == "99"


def test_neither_vocabulary_emits_qa_warning():
    qa = QACollector()
    normalize_report_rows([{"LocationID": "MW-1", "AnalyteName": "Benzene"}], qa)
    cats = [r.category for r in qa.records]
    assert "result_vocabulary_unrecognized" in cats


def test_max_result_dataset_no_longer_drops_canonical_rows():
    """Issue #339: this returned zero records, silently."""
    records = build_max_result_dataset([CANONICAL_ROW],
                                       screening_levels={"Benzene": 5.0})
    assert len(records) == 1
    assert records[0].max_result_value == 50.0
    assert records[0].has_exceedance is True


def test_exceedance_event_no_longer_misclassifies_canonical_detect():
    """Issue #339: a detected 50 ug/L read as a nondetect."""
    records = build_exceedance_event([CANONICAL_ROW], {"Benzene": 5.0},
                                     rule="max_exceedance_per_location")
    assert len(records) == 1
    assert records[0].has_detection is True
    assert records[0].has_exceedance is True
    assert records[0].result_value == 50.0


def test_compliance_summary_counts_canonical_detect():
    result = build_compliance_summary([CANONICAL_ROW],
                                      screening_levels={"Benzene": 5.0})
    assert result.records[0].ever_detected is True
    assert result.records[0].ever_exceeded is True


def test_report_vocabulary_input_is_unchanged_by_normalization():
    """The existing vocabulary must keep working identically."""
    assert build_max_result_dataset(
        [REPORT_ROW], screening_levels={"Benzene": 5.0}
    )[0].max_result_value == 50.0


def test_soil_and_trend_loaders_accept_canonical_csv(tmp_path):
    from autogis.core.envmon.soil_interval_selector import load_soil_results_csv
    from autogis.core.envmon.well_trend_charts import load_history_csv

    path = tmp_path / "canonical.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "LocationID", "AnalyteName", "SampleDate", "TopDepthFt",
            "BottomDepthFt", "ResultNumeric", "Qualifier", "Units",
            "ScreeningLevel", "ExceedsScreeningLevel"])
        w.writeheader()
        w.writerow({"LocationID": "SB-1", "AnalyteName": "Lead",
                    "SampleDate": "2026-07-01", "TopDepthFt": "0",
                    "BottomDepthFt": "2", "ResultNumeric": "50",
                    "Qualifier": "", "Units": "mg/kg",
                    "ScreeningLevel": "10", "ExceedsScreeningLevel": "True"})

    intervals = load_soil_results_csv(path)
    assert intervals[0].result_value == 50.0
    assert intervals[0].is_detect is True
    assert intervals[0].units == "mg/kg"

    series = load_history_csv(path)
    assert series and series[0].values == [50.0]


# --------------------------------------------------------------- #376 --
@pytest.mark.parametrize("bad", ["not-a-date", "2026-13-01", "20260701",
                                 "07/01/2026", "2026-7-1"])
def test_validate_iso_date_rejects_malformed(bad):
    with pytest.raises(ValueError, match="not a valid ISO date"):
        validate_iso_date(bad, "date_from")


@pytest.mark.parametrize("good", [None, "", "2026-07-01"])
def test_validate_iso_date_accepts_valid(good):
    assert validate_iso_date(good, "date_from") == good


def test_max_result_dataset_rejects_malformed_date_from():
    """Issue #376: this silently returned zero rows and exited 0."""
    with pytest.raises(ValueError, match="not a valid ISO date"):
        build_max_result_dataset([REPORT_ROW], date_from="not-a-date")


def test_compliance_summary_rejects_malformed_date_from():
    with pytest.raises(ValueError, match="not a valid ISO date"):
        build_compliance_summary([REPORT_ROW], date_from="not-a-date")


def test_exceedance_event_rejects_malformed_event_date():
    with pytest.raises(ValueError, match="not a valid ISO date"):
        build_exceedance_event([REPORT_ROW], {}, rule="specific_event_date",
                               event_date="not-a-date")


def test_exceedance_event_rejects_malformed_date_range():
    with pytest.raises(ValueError, match="not a valid ISO date"):
        build_exceedance_event([REPORT_ROW], {}, rule="date_range_latest",
                               date_range=("2026-01-01", "bogus"))


def test_valid_date_filter_still_selects_rows():
    records = build_max_result_dataset([REPORT_ROW],
                                       screening_levels={"Benzene": 5.0},
                                       date_from="2026-01-01",
                                       date_to="2026-12-31")
    assert len(records) == 1
