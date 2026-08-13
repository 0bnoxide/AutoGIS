"""Unit tests for validate_schedule."""
from autogis.core.common.qa import QACollector
from autogis.core.envmon.validate_schedule import validate_schedule

GOOD = {
    "site_id": "H281",
    "event_label": "2026Q2",
    "wells": ["MW-1", "MW-2"],
    "required_analytes": ["Benzene", "Toluene"],
}
DICT = {"Benzene", "Toluene", "Ethylbenzene"}


def test_valid_schedule():
    qa = QACollector()
    ok = validate_schedule(GOOD, DICT, qa=qa)
    assert ok is True
    assert not any(r.severity == "ERROR" for r in qa.records)


def test_missing_site_id():
    s = {**GOOD, "site_id": ""}
    qa = QACollector()
    ok = validate_schedule(s, DICT, qa=qa)
    assert ok is False
    assert any(r.category == "missing_site_id" for r in qa.records)


def test_missing_event_label():
    s = {**GOOD, "event_label": ""}
    qa = QACollector()
    ok = validate_schedule(s, DICT, qa=qa)
    assert ok is False
    assert any(r.category == "missing_event_label" for r in qa.records)


def test_missing_wells():
    s = {**GOOD, "wells": []}
    qa = QACollector()
    ok = validate_schedule(s, DICT, qa=qa)
    assert ok is False
    assert any(r.category == "missing_wells" for r in qa.records)


def test_duplicate_well_warns():
    s = {**GOOD, "wells": ["MW-1", "MW-1"]}
    qa = QACollector()
    validate_schedule(s, DICT, qa=qa)
    assert any(r.category == "duplicate_well" for r in qa.records)


def test_unknown_analyte_warns():
    s = {**GOOD, "required_analytes": ["Benzene", "Xylene"]}
    qa = QACollector()
    validate_schedule(s, DICT, qa=qa)
    assert any(r.category == "unknown_analyte" for r in qa.records)


def test_no_analyte_dict_skips_analyte_check():
    s = {**GOOD, "required_analytes": ["Unknown"]}
    qa = QACollector()
    ok = validate_schedule(s, None, qa=qa)
    assert ok is True  # no ERROR, just no dict to check against


def test_well_analytes_unknown_well_warns():
    s = {**GOOD, "well_analytes": {"MW-99": ["Benzene"]}}
    qa = QACollector()
    validate_schedule(s, DICT, qa=qa)
    assert any(r.category == "unknown_well_in_overrides" for r in qa.records)


def test_no_required_analytes_warns():
    s = {**GOOD, "required_analytes": []}
    qa = QACollector()
    ok = validate_schedule(s, DICT, qa=qa)
    assert ok is True  # warning only, not error
    assert any(r.category == "no_required_analytes" for r in qa.records)


def test_qa_info_emitted():
    qa = QACollector()
    validate_schedule(GOOD, DICT, qa=qa)
    assert any(r.category == "validate_schedule_complete" for r in qa.records)
