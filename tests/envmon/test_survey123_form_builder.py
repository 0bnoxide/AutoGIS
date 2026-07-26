"""Tests for survey123_form_builder — fully arcpy-free."""
import pytest


SITE = {
    "site_id": "H281",
    "site_name": "H281 Glasgow",
}

EVENT = {
    "analyte_groups": {
        "VOCs": ["Benzene", "Toluene"],
        "Metals": ["Arsenic"],
    },
    "crew_list": ["Alice Smith", "Bob Jones"],
    "coc_prefix": "H281-COC",
    "matrices": ["GW"],
    "location_ids": ["MW-1", "MW-2", "MW-3"],
}

ADICT = {
    "analytes": {
        "Benzene": {"abbreviation": "B",
                    "default_units_by_matrix": {"GW": "ug/L"},
                    "display_order": 10},
        "Toluene": {"abbreviation": "T",
                    "default_units_by_matrix": {"GW": "ug/L"},
                    "display_order": 20},
        "Arsenic": {"abbreviation": "As",
                    "default_units_by_matrix": {"GW": "ug/L"},
                    "display_order": 30},
    }
}


@pytest.fixture
def wb():
    from autogis.core.envmon.survey123_form_builder import build_xlsform
    return build_xlsform(SITE, EVENT, ADICT)


def test_workbook_has_three_sheets(wb):
    assert set(wb.sheetnames) == {"survey", "choices", "settings"}


def test_survey_sheet_has_header_row(wb):
    ws = wb["survey"]
    headers = [ws.cell(1, c).value for c in range(1, 6)]
    assert "type" in headers
    assert "name" in headers
    assert "label" in headers


def test_survey_contains_required_top_level_questions(wb):
    ws = wb["survey"]
    names = [ws.cell(r, 2).value for r in range(2, ws.max_row + 1)]
    for required in ("WellID", "SamplingDate", "Matrix", "SampleID",
                     "SampledBy", "COCNumber", "DepthToWater_ft",
                     "QAFlags", "Notes"):
        assert required in names, f"Missing question: {required}"


def test_sample_id_has_calculate_type(wb):
    ws = wb["survey"]
    for r in range(2, ws.max_row + 1):
        if ws.cell(r, 2).value == "SampleID":
            assert ws.cell(r, 1).value == "calculate"
            calc = ws.cell(r, 6).value or ""
            assert "${WellID}" in calc
            assert "${SamplingDate}" in calc
            assert "${Matrix}" in calc
            assert "${QAFlags}" in calc
            return
    pytest.fail("SampleID row not found")


def test_sample_id_calc_comes_from_shared_contract(wb):
    from autogis.core.envmon.sample_id import xform_sample_id_calc
    ws = wb["survey"]
    for r in range(2, ws.max_row + 1):
        if ws.cell(r, 2).value == "SampleID":
            assert ws.cell(r, 6).value == xform_sample_id_calc()
            return
    pytest.fail("SampleID row not found")


def test_field_duplicate_reuses_the_single_qa_flags_question(wb):
    """One affordance only. A second question (the withdrawn IsFieldDup) let a
    crew tick the ADR-0021 flag, leave the other at its default, and produce a
    SampleID identical to the primary — which append_records_idempotent then
    drops at SEV_INFO duplicate_key_skipped."""
    ws = wb["survey"]
    rows = {ws.cell(r, 2).value: ws.cell(r, 1).value
            for r in range(2, ws.max_row + 1)}
    assert rows.get("QAFlags") == "select_multiple qa_flags"
    assert "IsFieldDup" not in rows

    choices = wb["choices"]
    pairs = {(choices.cell(r, 1).value, choices.cell(r, 2).value)
             for r in range(2, choices.max_row + 1)}
    assert ("qa_flags", "field_dup") in pairs
    # the yes_no list existed only for the withdrawn question
    assert not any(lst == "yes_no" for lst, _ in pairs)


def test_analyte_groups_produce_begin_end_group(wb):
    ws = wb["survey"]
    types = [ws.cell(r, 1).value for r in range(2, ws.max_row + 1)]
    assert types.count("begin_group") == 2   # VOCs + Metals
    assert types.count("end_group") == 2


def test_analyte_field_label_includes_abbreviation_and_units(wb):
    ws = wb["survey"]
    labels = {ws.cell(r, 2).value: ws.cell(r, 3).value
              for r in range(2, ws.max_row + 1)}
    benzene_field = next(
        (n for n in labels if n and "Benzene" in n or
         (n and labels[n] and "B (" in str(labels[n]))), None)
    # Find any label matching "B (ug/L)"
    all_labels = list(labels.values())
    assert any("B (ug/L)" in str(l) for l in all_labels if l), \
        f"Expected 'B (ug/L)' in labels, got: {all_labels}"


def test_choices_sheet_has_well_list(wb):
    ws = wb["choices"]
    list_names = [ws.cell(r, 1).value for r in range(2, ws.max_row + 1)]
    assert "well_list" in list_names
    names = [ws.cell(r, 2).value for r in range(2, ws.max_row + 1)
             if ws.cell(r, 1).value == "well_list"]
    assert "MW-1" in names
    assert "MW-3" in names


def test_choices_sheet_has_matrix_list(wb):
    ws = wb["choices"]
    names = [ws.cell(r, 2).value for r in range(2, ws.max_row + 1)
             if ws.cell(r, 1).value == "matrix_list"]
    assert "GW" in names


def test_choices_sheet_has_crew_list(wb):
    ws = wb["choices"]
    labels = [ws.cell(r, 3).value for r in range(2, ws.max_row + 1)
              if ws.cell(r, 1).value == "crew_list"]
    assert "Alice Smith" in labels
    assert "Bob Jones" in labels


def test_settings_sheet_has_form_title(wb):
    ws = wb["settings"]
    headers = [ws.cell(1, c).value for c in range(1, 5)]
    assert "form_title" in headers
    values = [ws.cell(2, c).value for c in range(1, 5)]
    assert any(v and "H281" in str(v) for v in values)


def test_build_xlsform_returns_saveable_workbook(tmp_path, wb):
    out = tmp_path / "form.xlsx"
    wb.save(str(out))
    assert out.exists() and out.stat().st_size > 0
