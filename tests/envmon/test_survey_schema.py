"""Tests for survey_schema — XLSForm reader, validator, differ. Arcpy-free."""
import openpyxl
import pytest

from autogis.core.envmon.survey_schema import (
    CLASS_DESTRUCTIVE, CLASS_REVIEW, CLASS_SAFE,
    FormSchema, SurveyQuestion, read_xlsform,
)


def make_form(tmp_path, survey_rows, choices_rows=None, settings=None,
              survey_headers=("type", "name", "label", "hint", "required",
                              "calculation", "appearance", "default"),
              name="form.xlsx"):
    """Write a minimal XLSForm workbook and return its path."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("survey")
    ws.append(list(survey_headers))
    for r in survey_rows:
        ws.append(list(r))
    cs = wb.create_sheet("choices")
    cs.append(["list_name", "name", "label"])
    for r in (choices_rows or []):
        cs.append(list(r))
    if settings is not None:
        st = wb.create_sheet("settings")
        st.append(list(settings.keys()))
        st.append(list(settings.values()))
    p = tmp_path / name
    wb.save(p)
    return p


def test_reader_maps_columns_by_header_not_position(tmp_path):
    p = make_form(
        tmp_path,
        [("Notes", "text", "Notes label")],         # data in header order
        survey_headers=("name", "type", "label"),   # shuffled headers
    )
    schema = read_xlsform(p)
    q = schema.questions[0]
    assert (q.type, q.name, q.label) == ("text", "Notes", "Notes label")
    assert q.calculation == ""   # absent column -> ""


def test_reader_choices_and_settings(tmp_path):
    p = make_form(
        tmp_path,
        [("select_one yn", "Q1", "Q")],
        choices_rows=[("yn", "yes", "Yes"), ("yn", "no", "No")],
        settings={"form_title": "T", "form_id": "t_form", "version": "1"},
    )
    s = read_xlsform(p)
    assert s.choices["yn"] == [("yes", "Yes"), ("no", "No")]
    assert s.settings["form_id"] == "t_form"


def test_reader_missing_sheets_yield_empty_structures(tmp_path):
    wb = openpyxl.Workbook()
    wb.active.title = "survey"
    wb.active.append(["type", "name"])
    p = tmp_path / "bare.xlsx"
    wb.save(p)
    s = read_xlsform(p)
    assert s.questions == [] and s.choices == {} and s.settings == {}


def test_reader_keeps_structural_rows_in_order(tmp_path):
    p = make_form(tmp_path, [
        ("begin_group", "g1", "G"),
        ("decimal", "d1", "D"),
        ("end_group", "", ""),
    ])
    s = read_xlsform(p)
    assert [q.type for q in s.questions] == ["begin_group", "decimal",
                                             "end_group"]


# ---------------------------------------------------------------- validate

from autogis.core.common.qa import QACollector
from autogis.core.envmon.survey_schema import validate_form
from autogis.core.envmon.sample_id import xform_sample_id_calc


def _validate(tmp_path, survey_rows, choices_rows=None, settings=None, **kw):
    p = make_form(tmp_path, survey_rows, choices_rows, settings)
    qa = QACollector()
    validate_form(read_xlsform(p), qa, **kw)
    return qa


def _cats(qa):
    return {r.category for r in qa.records}


def test_missing_choices_sheet_is_error(tmp_path):
    wb = openpyxl.Workbook(); wb.active.title = "survey"
    wb.active.append(["type", "name"]); wb.active.append(["text", "A"])
    p = tmp_path / "f.xlsx"; wb.save(p)
    qa = QACollector(); validate_form(read_xlsform(p), qa)
    assert "missing_sheet" in _cats(qa)          # choices missing -> ERROR
    assert any(r.category == "settings_incomplete" and r.severity == "WARNING"
               for r in qa.records)              # settings missing -> WARNING


def test_duplicate_and_invalid_names(tmp_path):
    qa = _validate(tmp_path, [("text", "A", ""), ("text", "a", ""),
                              ("text", "9bad", "")])
    assert "duplicate_name" in _cats(qa)
    assert "invalid_name" in _cats(qa)


def test_missing_name_and_unknown_type(tmp_path):
    qa = _validate(tmp_path, [("text", "", ""), ("wat", "W", "")])
    assert "missing_name" in _cats(qa)
    assert "unknown_type" in _cats(qa)


def test_select_list_checks(tmp_path):
    qa = _validate(
        tmp_path,
        [("select_one nolist", "Q1", ""), ("select_one empty", "Q2", ""),
         ("select_one", "Q3", "")],
        choices_rows=[("empty", "", ""),               # invalid choice name
                      ("dup", "x", "X"), ("dup", "x", "X2")],
    )
    for cat in ("unknown_choice_list", "empty_choice_list", "unknown_type",
                "duplicate_choice", "invalid_choice_name"):
        assert cat in _cats(qa), cat


def test_unresolved_reference_and_backward_ref_ok(tmp_path):
    qa = _validate(tmp_path, [
        ("text", "A", ""),
        ("calculate", "C1", "", "", "", "concat(${A}, ${Missing})"),
        ("calculate", "C2", "", "", "", "${Later}"),
        ("text", "Later", ""),
    ])
    recs = [r for r in qa.records if r.category == "unresolved_reference"]
    assert len(recs) == 1 and "Missing" in recs[0].message


def test_unbalanced_group_detected(tmp_path):
    qa = _validate(tmp_path, [("begin_group", "g", ""), ("text", "A", ""),
                              ("end_repeat", "", "")])
    assert "unbalanced_group" in _cats(qa)


def test_odd_required_value_warns(tmp_path):
    qa = _validate(tmp_path, [("text", "A", "", "", "maybe")])
    rec = next(r for r in qa.records if r.category == "odd_required_value")
    assert rec.severity == "WARNING"


def test_sample_id_missing_is_error(tmp_path):
    qa = _validate(tmp_path, [("text", "A", "")])
    assert "sample_id_missing" in _cats(qa)


def test_sample_id_contract_match_and_mismatch(tmp_path):
    good = [("select_one well_list", "WellID", "", "", "yes"),
            ("date", "SamplingDate", "", "", "yes"),
            ("select_one matrix_list", "Matrix", "", "", "yes"),
            ("select_multiple qa_flags", "QAFlags", ""),
            ("calculate", "SampleID", "", "", "", xform_sample_id_calc())]
    choices = [("well_list", "MW-1", "MW-1"), ("matrix_list", "GW", "GW"),
               ("qa_flags", "field_dup", "Field Duplicate")]
    qa = _validate(tmp_path, good, choices)
    assert "sample_id_contract_mismatch" not in _cats(qa)

    bad = list(good); bad[4] = ("calculate", "SampleID", "", "", "", "${WellID}")
    qa2 = _validate(tmp_path, bad, choices)
    rec = next(r for r in qa2.records
               if r.category == "sample_id_contract_mismatch")
    assert rec.severity == "ERROR"


def test_sample_id_dup_leg_requires_flag_choice(tmp_path):
    rows = [("select_one well_list", "WellID", "", "", "yes"),
            ("date", "SamplingDate", "", "", "yes"),
            ("select_one matrix_list", "Matrix", "", "", "yes"),
            ("select_multiple qa_flags", "QAFlags", ""),
            ("calculate", "SampleID", "", "", "", xform_sample_id_calc())]
    choices = [("well_list", "MW-1", "MW-1"), ("matrix_list", "GW", "GW"),
               ("qa_flags", "resampled", "Resampled")]   # no field_dup
    qa = _validate(tmp_path, rows, choices)
    assert "sample_id_dup_leg" in _cats(qa)


def test_validation_complete_summary_present(tmp_path):
    qa = _validate(tmp_path, [("text", "A", "")])
    assert any(r.category == "validation_complete" and r.severity == "INFO"
               for r in qa.records)
