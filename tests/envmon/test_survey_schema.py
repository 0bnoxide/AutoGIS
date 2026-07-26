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
