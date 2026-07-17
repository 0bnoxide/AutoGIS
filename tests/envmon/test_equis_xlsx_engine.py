"""R1 (.xlsx engine) + R2 (header casefold + '#' strip) — slice 2b."""
import datetime
from pathlib import Path

import openpyxl

from autogis.core.common.qa import QACollector
from autogis.core.envmon.edd_profile import LabEDDProfile
from autogis.core.envmon.equis_reader import (
    _norm_header, _xlsx_cell_text, read_equis_xls,
)


def test_xlsx_cell_text_contract():
    # same contract as the xlrd _cell_text (R1)
    assert _xlsx_cell_text(None) == ""
    assert _xlsx_cell_text("  x  ") == "x"
    assert _xlsx_cell_text(5.0) == "5"
    assert _xlsx_cell_text(5.5) == "5.5"
    assert _xlsx_cell_text(7) == "7"
    assert _xlsx_cell_text(datetime.datetime(2025, 3, 17, 14, 2)) \
        == "03/17/2025 14:02"
    assert _xlsx_cell_text(datetime.datetime(2025, 3, 17)) == "03/17/2025"
    assert _xlsx_cell_text(datetime.date(2025, 3, 17)) == "03/17/2025"
    assert _xlsx_cell_text(datetime.time(14, 2)) == "14:02"


def test_norm_header_casefold_and_hash_strip():
    assert _norm_header("#Sample_ID") == "sample_id"
    assert _norm_header("Detect_Flag") == "detect_flag"
    assert _norm_header("sys_sample_code") == "sys_sample_code"   # WMRD no-op
    assert _norm_header("##x") == "#x"                            # ONE '#'
    assert _norm_header("") == ""


def _profile(**over):
    kw = dict(
        profile_id="t", lab_name="T", format="equis_xls",
        date_format="%m/%d/%Y", encoding="utf-8",
        columns={"sample_id": "sample_id"},
        matrix_map={}, nondetect_qualifiers=["U"],
        sample_sheet="Samples", result_sheet="Results", batch_sheet="",
        value_maps={"qc_sample_type": {"N": ""}},
    )
    kw.update(over)
    return LabEDDProfile(**kw)


def test_read_xlsx_titlecase_headers_land_on_equis_names(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Samples"
    ws.append(["#Sample_ID", "Sample_Type", "Sample_Source", "Matrix"])
    ws.append(["S-1", "N", "Field", "GW"])
    rs = wb.create_sheet("Results")
    rs.append(["#Sample_ID", "Result_Value", "Detect_Flag",
               "Analysis_Date", "Dilution_Factor"])
    rs.append(["S-1", 12.0, "Y", datetime.datetime(2025, 3, 17, 14, 2), 1])
    path = tmp_path / "t.xlsx"
    wb.save(path)

    rows = read_equis_xls(path, _profile(), QACollector())
    assert len(rows) == 1
    row = rows[0]
    assert row["__equis_result"] == "12"           # int-valued float
    assert row["analysis_date"] == "03/17/2025 14:02"
    assert row["sample_source"] == "Field"          # sample merge worked
    assert row["__source_row"] == 2


def test_read_xls_still_works_and_strips_hash(tmp_path):
    # the shipped WMRD .xls fixture goes through the same normalization
    fixture = (Path(__file__).parent.parent / "fixtures"
               / "wmrd_equis_fixture.xls")
    import autogis
    prof = LabEDDProfile.load(
        Path(autogis.__file__).parent / "config" / "lab_profiles"
        / "wmrd.yaml")
    rows = read_equis_xls(fixture, prof, QACollector())
    assert len(rows) == 9
    # header '#sys_sample_code' now lands casefolded+stripped
    assert "sys_sample_code" in rows[0]
