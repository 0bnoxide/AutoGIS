"""Unit tests for the pure helpers extracted from build_current_event's arcpy shell.

These cover the event-date parse and the InsertCursor row construction (field/
value alignment) — logic that previously only ran inside the arcpy write path.
"""
import datetime as dt

from autogis.core.common.qa import QACollector
from autogis.core.envmon.build_current_event import (
    build_insert_rows, parse_event_date,
)


def test_parse_event_date_valid():
    qa = QACollector()
    assert parse_event_date("2026-04-15", qa) == dt.datetime(2026, 4, 15)
    assert not qa.records


def test_parse_event_date_none_and_empty():
    qa = QACollector()
    assert parse_event_date(None, qa) is None
    assert parse_event_date("", qa) is None
    assert not qa.records


def test_parse_event_date_bad_format_warns_and_returns_none():
    qa = QACollector()
    assert parse_event_date("15/04/2026", qa) is None
    assert any(r.category == "bad_event_date" for r in qa.records)


def _wide(loc="MW-1", exceed=True):
    return {
        "LocationID": loc, "SampleID": "S1", "SampleDate": "2026-04-15",
        "DepthIntervalText": "",
        "HasExceedance": exceed, "HasDetection": True,
        "HasOnlyNonDetects": False, "HasMissingRequiredAnalytes": False,
        "LabelText_Fallback": "Benzene 5.0",
        "results": {"Benzene": {"DisplayText": "5.0"}, "Toluene": None},
    }


def test_build_insert_rows_field_alignment():
    rows = build_insert_rows(
        [_wide()], ["Benzene", "Toluene"],
        site_id="H281", figure_spec_id="FS1",
        event_dt=dt.datetime(2026, 4, 15), matrix="GW")
    assert len(rows) == 1
    row = rows[0]
    # 13 base values + 2 analyte values
    assert len(row) == 13 + 2
    assert row[:4] == ["H281", "FS1", dt.datetime(2026, 4, 15), "GW"]
    # booleans coerced to int
    assert row[8] == 1 and row[9] == 1 and row[10] == 0 and row[11] == 0
    # analyte columns: Benzene DisplayText, Toluene missing -> "--"
    assert row[13] == "5.0"
    assert row[14] == "--"


def test_build_insert_rows_truncates_label_and_value():
    w = _wide()
    w["LabelText_Fallback"] = "x" * 5000
    w["results"]["Benzene"] = {"DisplayText": "y" * 200}
    rows = build_insert_rows([w], ["Benzene"], site_id="S", figure_spec_id="F",
                             event_dt=None, matrix="GW")
    row = rows[0]
    assert len(row[12]) == 2000   # LabelText_Fallback[:2000]
    assert len(row[13]) == 64     # analyte DisplayText[:64]


def test_build_insert_rows_empty_wide():
    assert build_insert_rows([], ["Benzene"], site_id="S", figure_spec_id="F",
                             event_dt=None, matrix="GW") == []
