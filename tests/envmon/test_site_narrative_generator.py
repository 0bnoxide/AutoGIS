from pathlib import Path
import pytest
from autogis.core.envmon.site_narrative_generator import (
    NarrativeSection, SiteNarrativeResult,
    build_highest_detections_section,
    build_exceedance_change_section,
    build_not_sampled_section,
    generate_site_narrative,
)

_MAX_RESULTS = [
    {"location_id": "MW-01", "analyte_name": "Benzene",
     "max_result_value": "12.0", "max_sample_date": "2026-06-15",
     "reported_units": "ug/L", "exceedance_ratio": "2.4", "has_exceedance": "True"},
    {"location_id": "MW-02", "analyte_name": "Toluene",
     "max_result_value": "85.0", "max_sample_date": "2026-06-15",
     "reported_units": "ug/L", "exceedance_ratio": "", "has_exceedance": "False"},
    {"location_id": "MW-03", "analyte_name": "Benzene",
     "max_result_value": "0.5", "max_sample_date": "2026-06-15",
     "reported_units": "ug/L", "exceedance_ratio": "0.1", "has_exceedance": "False"},
]

_CHANGE_LOG = [
    {"change_type": "exceedance_new", "location_id": "MW-04",
     "analyte_name": "Benzene", "new_value": "6.0", "old_value": "ND",
     "event_date": "2026-06-15"},
    {"change_type": "exceedance_resolved", "location_id": "MW-05",
     "analyte_name": "Arsenic", "new_value": "ND", "old_value": "12.0",
     "event_date": "2026-06-15"},
]

_PLAN = [
    {"SampleID": "S1", "LocationID": "MW-01"},
    {"SampleID": "S2", "LocationID": "MW-02"},
    {"SampleID": "S3", "LocationID": "MW-03"},
]
_RESULTS = [
    {"SampleID": "S1"}, {"SampleID": "S2"},
    # S3/MW-03 not in results
]


def test_highest_detections_top_n():
    section = build_highest_detections_section(_MAX_RESULTS, top_n=2)
    assert isinstance(section, NarrativeSection)
    assert "MW-01" in section.text
    assert "Benzene" in section.text


def test_highest_detections_exceedance_mentioned():
    section = build_highest_detections_section(_MAX_RESULTS, top_n=3,
                                               screening_levels={"Benzene": 5.0})
    assert "exceed" in section.text.lower() or "MCL" in section.text


def test_exceedance_change_new():
    section = build_exceedance_change_section(_CHANGE_LOG)
    assert "MW-04" in section.text
    assert "new exceedance" in section.text.lower() or "exceedance_new" in section.text.lower()


def test_exceedance_change_resolved():
    section = build_exceedance_change_section(_CHANGE_LOG)
    assert "MW-05" in section.text


def test_not_sampled_section():
    section = build_not_sampled_section(_PLAN, _RESULTS)
    assert "MW-03" in section.text


def test_all_sampled_no_missing():
    plan = [{"SampleID": "S1", "LocationID": "MW-01"}]
    results = [{"SampleID": "S1"}]
    section = build_not_sampled_section(plan, results)
    assert "all" in section.text.lower() or "0" in section.text


def test_blank_sample_id_not_reported_missing():
    plan = [
        {"SampleID": "S1", "LocationID": "MW-01"},
        {"SampleID": "", "LocationID": "MW-99"},
    ]
    results = [{"SampleID": "S1"}]
    section = build_not_sampled_section(plan, results)
    assert "MW-99" not in section.text
    assert "all" in section.text.lower() or "0" in section.text


def test_generate_narrative_full_text(tmp_path):
    result = generate_site_narrative(
        "H281", "Q1-2026",
        max_result_rows=_MAX_RESULTS,
        change_log_rows=_CHANGE_LOG,
        plan_rows=_PLAN,
        result_rows=_RESULTS,
    )
    assert len(result.full_text) > 50
    assert "H281" in result.full_text or "Q1-2026" in result.full_text


def test_generate_narrative_max_only(tmp_path):
    result = generate_site_narrative(
        "H281", "Q1-2026",
        max_result_rows=_MAX_RESULTS,
    )
    assert result.full_text
    assert "MW-01" in result.full_text
